from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Protocol

import httpx
from sqlalchemy.orm import Session, sessionmaker

from app.async_tasks.models import (
    AsyncExecutionCheckpoint,
    AsyncRunStatus,
    AsyncTaskCreate,
    NotificationStatus,
)
from app.async_tasks.policy import (
    STEP_LEVEL_EXECUTION_CONSTRAINTS,
    AsyncTaskPolicyGate,
)
from app.async_tasks.repository import AsyncTaskRepository
from app.audit import AuditWriter
from app.openclaw.errors import OpenClawTransportError

if TYPE_CHECKING:
    from app.openclaw.models import (
        OpenClawExecutionRequest,
        OpenClawExecutionResult,
    )
from app.orchestration.coding_governance import (
    CodingAssignment,
    GovernanceContractError,
    GovernedTestEvidence,
    validate_coding_completion,
)
from app.tasks import TaskRepository, TaskService, TaskStatus

RETRY_DELAYS_SECONDS = (5, 30)
_PYTEST_PASSED_PATTERN = re.compile(
    r"^(?P<count>[1-9][0-9]*) passed in [0-9]+(?:\.[0-9]+)?s$"
)


def _validate_governed_test_argv(
    assignment: CodingAssignment,
    argv: tuple[str, ...],
) -> None:
    if len(argv) < 3 or argv[:2] != ("-m", "pytest"):
        raise GovernanceContractError("governed test argv must invoke pytest")
    targets = argv[2:-1] if argv[-1] == "-q" else argv[2:]
    flags = argv[len(targets) + 2 :]
    if not targets or any(flag != "-q" for flag in flags):
        raise GovernanceContractError("governed pytest options are not approved")
    allowed_test_paths = {
        value.rstrip("/")
        for value in assignment.allowed_paths
        if value.startswith("tests/")
    }
    for target in targets:
        path = Path(target)
        target_is_allowed = target == "tests" or target.rstrip("/") in allowed_test_paths
        if (
            target.startswith("-")
            or path.is_absolute()
            or ".." in path.parts
            or not target_is_allowed
        ):
            raise GovernanceContractError("governed pytest target is not approved")

def verify_governed_tests(
    assignment: CodingAssignment,
) -> GovernedTestEvidence:
    """Run declared tests with the exact existing venv and no PATH fallback."""
    runtime = assignment.test_runtime
    if runtime is None:
        raise GovernanceContractError("governed test runtime is not declared")
    if runtime.allow_fallback:
        raise GovernanceContractError("governed test runtime fallback is forbidden")
    workspace = Path(assignment.workspace).resolve(strict=False)
    executable = Path(runtime.executable).resolve(strict=False)
    expected_executable = (workspace / ".venv" / "bin" / "python").resolve(
        strict=False
    )
    if executable != expected_executable:
        raise GovernanceContractError("test executable is not the workspace venv")
    _validate_governed_test_argv(assignment, runtime.argv)
    if not executable.is_file() or not os.access(executable, os.X_OK):
        raise GovernanceContractError("declared test executable is unavailable")
    try:
        completed = subprocess.run(
            [str(executable), *runtime.argv],
            cwd=str(workspace),
            capture_output=True,
            text=True,
            timeout=runtime.timeout_seconds,
            check=False,
            shell=False,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise GovernanceContractError(
            "declared governed tests could not execute"
        ) from error
    lines = completed.stdout.strip().splitlines()
    summaries = [
        match
        for line in lines
        if (match := _PYTEST_PASSED_PATTERN.fullmatch(line.strip())) is not None
    ]
    if (
        completed.returncode != 0
        or len(summaries) != 1
        or summaries[0].group(0) != lines[-1].strip()
    ):
        raise GovernanceContractError("declared governed tests did not pass")
    return GovernedTestEvidence(
        executable=str(executable),
        argv=runtime.argv,
        workspace=str(workspace),
        return_code=completed.returncode,
        passed=int(summaries[0].group("count")),
    )


def merge_governed_test_evidence(
    verification: object,
    evidence: GovernedTestEvidence,
) -> dict[str, Any]:
    """Preserve reported verification while adding core test evidence."""
    merged = dict(verification) if isinstance(verification, Mapping) else {
        "reported": verification
    }
    merged["core_governed_tests"] = evidence.model_dump(mode="json")
    return merged


class AsyncTaskExecutor(Protocol):
    async def execute(
        self,
        request: OpenClawExecutionRequest,
    ) -> OpenClawExecutionResult: ...


CoreStatusProbe = Callable[[], Awaitable[dict[str, Any]]]

class AsyncTaskWorker:
    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session],
        audit_writer: AuditWriter,
        policy_gate: AsyncTaskPolicyGate,
        executor: AsyncTaskExecutor,
        worker_id: str,
        lease_seconds: int,
        clock: Callable[[], datetime] | None = None,
        core_status_probe: CoreStatusProbe | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.audit_writer = audit_writer
        self.policy_gate = policy_gate
        self.executor = executor
        self.worker_id = worker_id
        self.lease_seconds = lease_seconds
        self.clock = clock or (lambda: datetime.now(UTC))
        self.core_status_probe = (
            core_status_probe or self._probe_local_core_status
        )

    async def run_once(self) -> bool:
        now = self._now()
        with self.session_factory() as session:
            repository = AsyncTaskRepository(
                session,
                audit_writer=self.audit_writer,
            )
            run = repository.claim_next(
                worker_id=self.worker_id,
                now=now,
                lease_seconds=self.lease_seconds,
            )
            if run is None:
                session.rollback()
                return False

            task_service = self._task_service(session)
            task = task_service.get(run.task_id)
            request = AsyncTaskCreate.model_validate_json(
                run.request_json
            )

            if request.governed_coding is not None:
                try:
                    request.governed_coding.validate_workspace()
                except GovernanceContractError as error:
                    repository.transition(
                        run.id,
                        AsyncRunStatus.BLOCKED,
                        now=now,
                        error_code="governance_contract_violation",
                        error_message=str(error),
                    )
                    task_service.transition(
                        task.id,
                        TaskStatus.BLOCKED,
                        result_summary=str(error),
                    )
                    self._mark_terminal_notification(
                        repository,
                        run.id,
                        run.source_chat_id,
                        now,
                    )
                    session.commit()
                    return True

            decision = self.policy_gate.evaluate(request)

            if not decision.allowed:
                repository.transition(
                    run.id,
                    AsyncRunStatus.BLOCKED,
                    now=now,
                    error_code=decision.reason_code,
                    error_message=decision.message,
                )
                task_service.transition(
                    task.id,
                    TaskStatus.BLOCKED,
                    result_summary=decision.message,
                )
                self._mark_terminal_notification(
                    repository,
                    run.id,
                    run.source_chat_id,
                    now,
                )
                session.commit()
                return True

            checkpoint = AsyncExecutionCheckpoint(
                stage="running",
                message="OpenClaw HTTP execution started.",
                uncertain_side_effect=False,
                updated_at=now,
            )
            repository.transition(
                run.id,
                AsyncRunStatus.RUNNING,
                now=now,
                checkpoint_json=checkpoint.model_dump_json(),
            )
            if task.status in {
                TaskStatus.QUEUED,
                TaskStatus.VERIFYING,
            }:
                task_service.transition(
                    task.id,
                    TaskStatus.RUNNING,
                )
            session.commit()

        if self._is_core_health_ready_workflow(request):
            result = await self._execute_core_health_ready_workflow()
            self._persist_result(
                run.id,
                run.task_id,
                result,
            )
            return True

        from app.openclaw.models import OpenClawExecutionRequest
        execution_request = OpenClawExecutionRequest(
            task_id=run.task_id,
            run_id=run.id,
            attempt=run.attempt,
            idempotency_key=f"{run.id}:{run.attempt}",
            project_id=request.project_id,
            goal=request.goal,
            mode=request.mode.value,
            workspace=request.workspace,
            constraints=self._execution_constraints(request),
            governed_coding=request.governed_coding,
        )

        try:
            result = await self.executor.execute(
                execution_request
            )
        except OpenClawTransportError as error:
            self._handle_transport_error(
                run.id,
                run.task_id,
                error,
            )
            return True

        self._persist_result(
            run.id,
            run.task_id,
            result,
        )
        return True

    @staticmethod
    def _execution_constraints(
        request: AsyncTaskCreate,
    ) -> tuple[str, ...]:
        if request.approval_required or request.risk_level >= 2:
            return tuple(
                dict.fromkeys(
                    request.constraints
                    + STEP_LEVEL_EXECUTION_CONSTRAINTS
                )
            )
        return request.constraints

    @staticmethod
    def _is_core_health_ready_workflow(
        request: AsyncTaskCreate,
    ) -> bool:
        goal = request.goal.casefold()
        return (
            "/health" in goal
            and "/ready" in goal
            and (
                "core" in goal
                or "ánh dương" in goal
                or "anh duong" in goal
            )
        )

    async def _execute_core_health_ready_workflow(
        self,
    ) -> OpenClawExecutionResult:
        statuses = await self.core_status_probe()
        health = statuses.get("health", {})
        ready = statuses.get("ready", {})
        health_ok = (
            isinstance(health, dict)
            and health.get("http_status") == 200
            and health.get("status") == "ok"
        )
        ready_ok = (
            isinstance(ready, dict)
            and ready.get("http_status") == 200
            and ready.get("status") == "ready"
        )
        outcome: Literal["completed", "blocked"] = (
            "completed" if health_ok and ready_ok else "blocked"
        )
        summary = (
            "Đã kiểm tra read-only /health và /ready của Ánh Dương Core: "
            f"/health={health.get('status')!s}, /ready={ready.get('status')!s}."
            if outcome == "completed"
            else (
                "Không xác minh được đầy đủ /health và /ready của "
                "Ánh Dương Core bằng kiểm tra read-only nội bộ."
            )
        )
        from app.openclaw.models import OpenClawExecutionResult
        return OpenClawExecutionResult(
            outcome=outcome,
            summary=summary,
            artifacts={
                "health": health,
                "ready": ready,
                "changes_made": "none",
                "file_changes": "none",
                "config_changes": "none",
                "service_restarts": "none",
            },
            verification={
                "method": "core_internal_http_get",
                "constraints_respected": [
                    "no_file_changes",
                    "no_config_changes",
                    "no_service_restart",
                    "no_model_provider_change",
                ],
            },
            files_changed=(),
            commands_run=(),
            tests=(),
            profile="CE-2",
        )

    @staticmethod
    async def _probe_local_core_status() -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=5.0) as client:
            health_response = await client.get(
                "http://127.0.0.1:8790/health"
            )
            ready_response = await client.get(
                "http://127.0.0.1:8790/ready"
            )
        return {
            "health": {
                "http_status": health_response.status_code,
                **health_response.json(),
            },
            "ready": {
                "http_status": ready_response.status_code,
                **ready_response.json(),
            },
        }

    def _handle_transport_error(
        self,
        run_id: str,
        task_id: str,
        error: OpenClawTransportError,
    ) -> None:
        now = self._now()
        safe_error_message = (
            "OpenClaw returned an invalid execution result contract."
            if error.code == "invalid_response_contract"
            else str(error)
        )
        with self.session_factory() as session:
            repository = AsyncTaskRepository(
                session,
                audit_writer=self.audit_writer,
            )
            run = repository.get(run_id)
            if run.status is AsyncRunStatus.CANCELLED:
                return

            task_service = self._task_service(session)
            if (
                error.retryable
                and not error.uncertain_side_effect
                and run.attempt < run.max_attempts
            ):
                delay = RETRY_DELAYS_SECONDS[
                    min(
                        run.attempt - 1,
                        len(RETRY_DELAYS_SECONDS) - 1,
                    )
                ]
                repository.schedule_retry(
                    run_id,
                    now=now,
                    delay_seconds=delay,
                    error_code=error.code,
                    error_message=safe_error_message,
                )
                session.commit()
                return

            target_run = (
                AsyncRunStatus.BLOCKED
                if error.uncertain_side_effect
                else AsyncRunStatus.FAILED
            )
            target_task = (
                TaskStatus.BLOCKED
                if error.uncertain_side_effect
                else TaskStatus.FAILED
            )
            terminal_checkpoint = AsyncExecutionCheckpoint(
                stage="terminal",
                message=safe_error_message,
                uncertain_side_effect=error.uncertain_side_effect,
                updated_at=now,
            )
            terminal = repository.transition(
                run_id,
                target_run,
                now=now,
                checkpoint_json=terminal_checkpoint.model_dump_json(),
                error_code=error.code,
                error_message=safe_error_message,
            )
            task_service.transition(
                task_id,
                target_task,
                result_summary=safe_error_message,
            )
            self._mark_terminal_notification(
                repository,
                run_id,
                terminal.source_chat_id,
                now,
            )
            session.commit()

    def _persist_result(
        self,
        run_id: str,
        task_id: str,
        result: OpenClawExecutionResult,
    ) -> None:
        now = self._now()
        result_json = result.model_dump_json()
        with self.session_factory() as session:
            repository = AsyncTaskRepository(
                session,
                audit_writer=self.audit_writer,
            )
            current = repository.get(run_id)
            if current.status is AsyncRunStatus.CANCELLED:
                return

            task_service = self._task_service(session)
            request = AsyncTaskCreate.model_validate_json(
                current.request_json
            )

            # Completion gate for governed coding assignments
            if request.governed_coding is not None:
                if result.outcome == "completed":
                    if result.governance_result is None:
                        err_code = "governance_result_missing"
                        err_msg = "Completed governed coding run missing governance_result."
                        repository.transition(
                            run_id,
                            AsyncRunStatus.BLOCKED,
                            now=now,
                            result_json=result_json,
                            external_run_id=result.external_run_id,
                            error_code=err_code,
                            error_message=err_msg,
                        )
                        task_service.transition(
                            task_id,
                            TaskStatus.BLOCKED,
                            result_summary=err_msg,
                        )
                        self._mark_terminal_notification(
                            repository,
                            run_id,
                            current.source_chat_id,
                            now,
                        )
                        session.commit()
                        return
                    try:
                        validate_coding_completion(
                            request.governed_coding,
                            result.governance_result,
                        )
                        test_evidence = verify_governed_tests(
                            request.governed_coding
                        )
                        result = result.model_copy(
                            update={
                                "verification": merge_governed_test_evidence(
                                    result.verification,
                                    test_evidence,
                                )
                            }
                        )
                        result_json = result.model_dump_json()
                    except GovernanceContractError as error:
                        err_code = "governance_contract_violation"
                        err_msg = str(error)
                        repository.transition(
                            run_id,
                            AsyncRunStatus.BLOCKED,
                            now=now,
                            result_json=result_json,
                            external_run_id=result.external_run_id,
                            error_code=err_code,
                            error_message=err_msg,
                        )
                        task_service.transition(
                            task_id,
                            TaskStatus.BLOCKED,
                            result_summary=err_msg,
                        )
                        self._mark_terminal_notification(
                            repository,
                            run_id,
                            current.source_chat_id,
                            now,
                        )
                        session.commit()
                        return

            repository.transition(
                run_id,
                AsyncRunStatus.VERIFYING,
                now=now,
                result_json=result_json,
                external_run_id=result.external_run_id,
            )
            task_service.transition(
                task_id,
                TaskStatus.VERIFYING,
            )

            if result.outcome == "completed":
                run_status = AsyncRunStatus.COMPLETED
                task_status = TaskStatus.COMPLETED
            elif result.outcome == "blocked":
                run_status = AsyncRunStatus.BLOCKED
                task_status = TaskStatus.BLOCKED
            else:
                run_status = AsyncRunStatus.FAILED
                task_status = TaskStatus.FAILED

            terminal = repository.transition(
                run_id,
                run_status,
                now=now,
                result_json=result_json,
                external_run_id=result.external_run_id,
            )
            task_service.transition(
                task_id,
                task_status,
                result_summary=result.summary,
            )
            self._mark_terminal_notification(
                repository,
                run_id,
                terminal.source_chat_id,
                now,
            )
            session.commit()

    @staticmethod
    def _mark_terminal_notification(
        repository: AsyncTaskRepository,
        run_id: str,
        source_chat_id: str | None,
        now: datetime,
    ) -> None:
        repository.mark_notification(
            run_id,
            status=(
                NotificationStatus.PENDING
                if source_chat_id
                else NotificationStatus.NOT_REQUIRED
            ),
            now=now,
        )

    def _task_service(
        self,
        session: Session,
    ) -> TaskService:
        return TaskService(
            TaskRepository(session),
            self.audit_writer,
        )

    def _now(self) -> datetime:
        value = self.clock()
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
