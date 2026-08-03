from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy.orm import Session, sessionmaker

from app.async_tasks.models import (
    AsyncExecutionCheckpoint,
    AsyncRunStatus,
    AsyncTaskCreate,
    NotificationStatus,
)
from app.async_tasks.policy import AsyncTaskPolicyGate
from app.async_tasks.repository import AsyncTaskRepository
from app.audit import AuditWriter
from app.openclaw import (
    OpenClawExecutionRequest,
    OpenClawExecutionResult,
    OpenClawTransportError,
)
from app.tasks import TaskRepository, TaskService, TaskStatus

RETRY_DELAYS_SECONDS = (5, 30)


class AsyncTaskExecutor(Protocol):
    async def execute(
        self,
        request: OpenClawExecutionRequest,
    ) -> OpenClawExecutionResult: ...


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
    ) -> None:
        self.session_factory = session_factory
        self.audit_writer = audit_writer
        self.policy_gate = policy_gate
        self.executor = executor
        self.worker_id = worker_id
        self.lease_seconds = lease_seconds
        self.clock = clock or (lambda: datetime.now(UTC))

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

        execution_request = OpenClawExecutionRequest(
            task_id=run.task_id,
            run_id=run.id,
            attempt=run.attempt,
            idempotency_key=f"{run.id}:{run.attempt}",
            project_id=request.project_id,
            goal=request.goal,
            mode=request.mode.value,
            workspace=request.workspace,
            constraints=request.constraints,
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

    def _handle_transport_error(
        self,
        run_id: str,
        task_id: str,
        error: OpenClawTransportError,
    ) -> None:
        now = self._now()
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
                    error_message=str(error),
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
            terminal = repository.transition(
                run_id,
                target_run,
                now=now,
                error_code=error.code,
                error_message=str(error),
            )
            task_service.transition(
                task_id,
                target_task,
                result_summary=str(error),
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

