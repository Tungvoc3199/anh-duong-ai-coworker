from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.async_tasks import (
    AsyncRunStatus,
    AsyncTaskCreate,
    AsyncTaskPolicyGate,
    AsyncTaskRepository,
    AsyncTaskService,
    AsyncTaskWorker,
)
from app.audit import AuditWriter
from app.db.base import Base
from app.db.models import ProjectRow
from app.db.session import create_db_engine
from app.openclaw import (
    OpenClawExecutionRequest,
    OpenClawExecutionResult,
    OpenClawTransportError,
)
from app.tasks import TaskRepository, TaskService, TaskStatus

NOW = datetime.now(UTC) + timedelta(hours=1)


class SequenceExecutor:
    def __init__(self, outcomes: list[object]) -> None:
        self.outcomes = outcomes
        self.requests: list[OpenClawExecutionRequest] = []

    async def execute(
        self,
        request: OpenClawExecutionRequest,
    ) -> OpenClawExecutionResult:
        self.requests.append(request)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        assert isinstance(outcome, OpenClawExecutionResult)
        return outcome


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    database_url = (
        "sqlite+pysqlite:///"
        f"{tmp_path / 'async-worker.db'}"
    )
    runtime_engine = create_db_engine(database_url)
    Base.metadata.create_all(runtime_engine)
    try:
        yield runtime_engine
    finally:
        runtime_engine.dispose()


@pytest.fixture
def session_factory(
    engine: Engine,
) -> sessionmaker[Session]:
    return sessionmaker(
        bind=engine,
        class_=Session,
        expire_on_commit=False,
        autoflush=False,
    )


def _audit(tmp_path: Path) -> AuditWriter:
    return AuditWriter(
        tmp_path / "worker-audit.jsonl",
        fsync=False,
    )


def _seed_run(
    session_factory: sessionmaker[Session],
    tmp_path: Path,
    *,
    key: str,
    goal: str = "Complete a deterministic test task",
    risk_level: int = 0,
    approval_required: bool = False,
) -> tuple[str, str]:
    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    with session_factory() as session:
        project = ProjectRow(
            id=f"proj_{key}",
            name=f"Project {key}",
            slug=f"project-{key}",
            status="active",
        )
        session.add(project)
        session.flush()

        service = AsyncTaskService(
            task_service=TaskService(
                TaskRepository(session),
                _audit(tmp_path),
            ),
            repository=AsyncTaskRepository(session),
            policy_gate=AsyncTaskPolicyGate((tmp_path,)),
        )
        accepted = service.create(
            AsyncTaskCreate(
                project_id=project.id,
                title="Worker test",
                goal=goal,
                risk_level=risk_level,
                approval_required=approval_required,
                workspace=str(workspace),
                source_channel="telegram",
                source_chat_id="chat-test",
                idempotency_key=f"telegram:{key}",
            )
        )
        session.commit()
        return accepted.task_id, accepted.run_id


def _worker(
    *,
    session_factory: sessionmaker[Session],
    tmp_path: Path,
    executor: Any,
    clock: list[datetime],
    core_status_probe: Any = None,
) -> AsyncTaskWorker:
    return AsyncTaskWorker(
        session_factory=session_factory,
        audit_writer=_audit(tmp_path),
        policy_gate=AsyncTaskPolicyGate((tmp_path,)),
        executor=executor,
        worker_id="worker-1",
        lease_seconds=900,
        clock=lambda: clock[0],
        core_status_probe=core_status_probe,
    )


@pytest.mark.asyncio
async def test_worker_completes_run_and_task(
    session_factory: sessionmaker[Session],
    tmp_path: Path,
) -> None:
    task_id, run_id = _seed_run(
        session_factory,
        tmp_path,
        key="success",
    )
    executor = SequenceExecutor(
        [
            OpenClawExecutionResult(
                outcome="completed",
                summary="Worker completed the task.",
                artifacts=("artifact.zip",),
                verification=("pytest passed",),
                files_changed=("calculate.py",),
                commands_run=("pytest -q",),
                tests=(
                    {
                        "name": "pytest",
                        "status": "PASS",
                    },
                ),
                model="cx/gpt-5.5",
                provider="router9",
                profile="CE-2",
                duration_ms=1234,
                error_code=None,
                external_run_id="resp_1",
            )
        ]
    )
    worker = _worker(
        session_factory=session_factory,
        tmp_path=tmp_path,
        executor=executor,
        clock=[NOW],
    )

    processed = await worker.run_once()

    with session_factory() as session:
        run = AsyncTaskRepository(session).get(run_id)
        task = TaskService(
            TaskRepository(session),
            _audit(tmp_path),
        ).get(task_id)

    assert processed is True
    assert run.status is AsyncRunStatus.COMPLETED
    assert run.notification_status.value == "pending"
    assert task.status is TaskStatus.COMPLETED
    assert task.result_summary == "Worker completed the task."
    result_json = json.loads(run.result_json or "{}")
    assert result_json["files_changed"] == ["calculate.py"]
    assert result_json["commands_run"] == ["pytest -q"]
    assert result_json["tests"] == [
        {
            "name": "pytest",
            "status": "PASS",
        }
    ]
    assert result_json["model"] == "cx/gpt-5.5"
    assert result_json["provider"] == "router9"
    assert result_json["profile"] == "CE-2"
    assert result_json["duration_ms"] == 1234
    assert result_json["error_code"] is None
    request = executor.requests[0]
    assert request.idempotency_key == f"{run_id}:1"


@pytest.mark.asyncio
async def test_worker_completes_core_health_ready_workflow_locally(
    session_factory: sessionmaker[Session],
    tmp_path: Path,
) -> None:
    task_id, run_id = _seed_run(
        session_factory,
        tmp_path,
        key="core-health-ready",
        goal=(
            "Thực hiện một workflow read-only: kiểm tra trạng thái "
            "/health và /ready của Ánh Dương Core, không sửa file, "
            "không restart service, không thay đổi cấu hình, rồi báo "
            "lại kết quả cho anh."
        ),
    )
    executor = SequenceExecutor([])

    async def core_status_probe() -> dict[str, object]:
        return {
            "health": {"http_status": 200, "status": "ok"},
            "ready": {"http_status": 200, "status": "ready"},
        }

    worker = _worker(
        session_factory=session_factory,
        tmp_path=tmp_path,
        executor=executor,
        clock=[NOW],
        core_status_probe=core_status_probe,
    )

    processed = await worker.run_once()

    with session_factory() as session:
        run = AsyncTaskRepository(session).get(run_id)
        task = TaskService(
            TaskRepository(session),
            _audit(tmp_path),
        ).get(task_id)

    assert processed is True
    assert executor.requests == []
    assert run.status is AsyncRunStatus.COMPLETED
    assert run.notification_status.value == "pending"
    assert task.status is TaskStatus.COMPLETED
    checkpoint_message = run.checkpoint_json or ""
    assert "OpenClaw" not in checkpoint_message
    result_json = json.loads(run.result_json or "{}")
    assert result_json["outcome"] == "completed"
    assert result_json["artifacts"]["health"]["status"] == "ok"
    assert result_json["artifacts"]["ready"]["status"] == "ready"
    assert result_json["commands_run"] == []
    assert result_json["files_changed"] == []


@pytest.mark.asyncio
async def test_worker_executes_safe_prefix_for_approval_required_facebook_task(
    session_factory: sessionmaker[Session],
    tmp_path: Path,
) -> None:
    task_id, run_id = _seed_run(
        session_factory,
        tmp_path,
        key="facebook-safe-prefix",
        goal=(
            "Research trang Facebook công khai của dự án, đọc và tóm tắt "
            "các bài viết liên quan. Nếu cần đăng/publish/send external "
            "thì dừng lại xin approval sau khi hoàn thành phần web read "
            "và summarize an toàn."
        ),
        risk_level=2,
        approval_required=True,
    )
    executor = SequenceExecutor(
        [
            OpenClawExecutionResult(
                outcome="blocked",
                summary=(
                    "Đã hoàn thành web read và summarize công khai; dừng "
                    "trước bước publish cần approval."
                ),
                artifacts={
                    "safe_steps_completed": [
                        "web_search_read",
                        "summarize",
                    ],
                    "blocked_step": "publish",
                },
                verification={"policy": "step_level_gate"},
            )
        ]
    )
    worker = _worker(
        session_factory=session_factory,
        tmp_path=tmp_path,
        executor=executor,
        clock=[NOW],
    )

    processed = await worker.run_once()

    with session_factory() as session:
        run = AsyncTaskRepository(session).get(run_id)
        task = TaskService(
            TaskRepository(session),
            _audit(tmp_path),
        ).get(task_id)

    assert processed is True
    assert run.status is AsyncRunStatus.BLOCKED
    assert task.status is TaskStatus.BLOCKED
    assert executor.requests
    execution_request = executor.requests[0]
    assert "complete_safe_steps_before_approval_gate" in execution_request.constraints
    assert (
        "hard_gate_publish_send_external_destructive_secret_cost"
        in execution_request.constraints
    )
    result_json = json.loads(run.result_json or "{}")
    assert result_json["artifacts"]["safe_steps_completed"] == [
        "web_search_read",
        "summarize",
    ]
    assert task.result_summary is not None
    assert "This action requires approval" not in task.result_summary


@pytest.mark.asyncio
async def test_worker_persists_structured_workflow_result(
    session_factory: sessionmaker[Session],
    tmp_path: Path,
) -> None:
    task_id, run_id = _seed_run(
        session_factory,
        tmp_path,
        key="structured-result",
    )
    executor = SequenceExecutor(
        [
            OpenClawExecutionResult(
                outcome="completed",
                summary="Structured workflow completed.",
                artifacts={
                    "checklist": [
                        {
                            "step": 1,
                            "name": "Xác nhận phạm vi kiểm tra",
                            "check": "Đảm bảo chỉ quan sát trạng thái Core.",
                            "readonly_rule": "Không chạy lệnh.",
                        }
                    ]
                },
                verification={
                    "method": "static_review_only",
                    "commands_run": 0,
                    "files_changed": 0,
                    "config_changed": False,
                    "services_restarted": False,
                    "notes": "No commands were run.",
                },
                external_run_id="resp_structured",
            )
        ]
    )
    worker = _worker(
        session_factory=session_factory,
        tmp_path=tmp_path,
        executor=executor,
        clock=[NOW],
    )

    processed = await worker.run_once()

    with session_factory() as session:
        run = AsyncTaskRepository(session).get(run_id)
        task = TaskService(
            TaskRepository(session),
            _audit(tmp_path),
        ).get(task_id)

    assert processed is True
    assert run.status is AsyncRunStatus.COMPLETED
    assert task.status is TaskStatus.COMPLETED
    assert run.external_run_id == "resp_structured"
    result_json = json.loads(run.result_json or "{}")
    assert result_json["artifacts"] == {
        "checklist": [
            {
                "step": 1,
                "name": "Xác nhận phạm vi kiểm tra",
                "check": "Đảm bảo chỉ quan sát trạng thái Core.",
                "readonly_rule": "Không chạy lệnh.",
            }
        ]
    }
    assert result_json["verification"] == {
        "method": "static_review_only",
        "commands_run": 0,
        "files_changed": 0,
        "config_changed": False,
        "services_restarted": False,
        "notes": "No commands were run.",
    }


@pytest.mark.asyncio
async def test_worker_uses_five_then_thirty_second_retries_and_fails_third(
    session_factory: sessionmaker[Session],
    tmp_path: Path,
) -> None:
    task_id, run_id = _seed_run(
        session_factory,
        tmp_path,
        key="retry",
    )
    executor = SequenceExecutor(
        [
            OpenClawTransportError(
                "connection_error",
                "temporary connection failure",
                retryable=True,
            ),
            OpenClawTransportError(
                "connection_error",
                "temporary connection failure",
                retryable=True,
            ),
            OpenClawTransportError(
                "connection_error",
                "temporary connection failure",
                retryable=True,
            ),
        ]
    )
    clock = [NOW]
    worker = _worker(
        session_factory=session_factory,
        tmp_path=tmp_path,
        executor=executor,
        clock=clock,
    )

    await worker.run_once()
    with session_factory() as session:
        first = AsyncTaskRepository(session).get(run_id)
    assert first.status is AsyncRunStatus.RETRY_WAIT
    assert first.run_after == NOW + timedelta(seconds=5)

    clock[0] = first.run_after
    await worker.run_once()
    with session_factory() as session:
        second = AsyncTaskRepository(session).get(run_id)
    assert second.status is AsyncRunStatus.RETRY_WAIT
    assert second.run_after == clock[0] + timedelta(seconds=30)

    clock[0] = second.run_after
    await worker.run_once()
    with session_factory() as session:
        final = AsyncTaskRepository(session).get(run_id)
        task = TaskService(
            TaskRepository(session),
            _audit(tmp_path),
        ).get(task_id)

    assert final.status is AsyncRunStatus.FAILED
    assert final.attempt == 3
    assert task.status is TaskStatus.FAILED


@pytest.mark.asyncio
async def test_uncertain_outcome_is_blocked_without_retry(
    session_factory: sessionmaker[Session],
    tmp_path: Path,
) -> None:
    task_id, run_id = _seed_run(
        session_factory,
        tmp_path,
        key="uncertain",
    )
    executor = SequenceExecutor(
        [
            OpenClawTransportError(
                "uncertain_outcome",
                "outcome is uncertain",
                retryable=False,
                uncertain_side_effect=True,
            )
        ]
    )
    worker = _worker(
        session_factory=session_factory,
        tmp_path=tmp_path,
        executor=executor,
        clock=[NOW],
    )

    await worker.run_once()

    with session_factory() as session:
        run = AsyncTaskRepository(session).get(run_id)
        task = TaskService(
            TaskRepository(session),
            _audit(tmp_path),
        ).get(task_id)

    assert run.status is AsyncRunStatus.BLOCKED
    assert run.attempt == 1
    assert task.status is TaskStatus.BLOCKED


@pytest.mark.asyncio
async def test_contract_error_terminalizes_and_worker_processes_next_run(
    session_factory: sessionmaker[Session],
    tmp_path: Path,
) -> None:
    first_task_id, first_run_id = _seed_run(
        session_factory,
        tmp_path,
        key="invalid-contract",
    )
    second_task_id, second_run_id = _seed_run(
        session_factory,
        tmp_path,
        key="after-invalid-contract",
    )
    secret = "token-super-secret"
    executor = SequenceExecutor(
        [
            OpenClawTransportError(
                "invalid_response_contract",
                f"Invalid OpenClaw response: {secret}",
                retryable=False,
                uncertain_side_effect=False,
            ),
            OpenClawExecutionResult(
                outcome="completed",
                summary="Next job completed.",
            ),
        ]
    )
    worker = _worker(
        session_factory=session_factory,
        tmp_path=tmp_path,
        executor=executor,
        clock=[NOW],
    )

    assert await worker.run_once() is True
    assert await worker.run_once() is True

    with session_factory() as session:
        repository = AsyncTaskRepository(session)
        first_run = repository.get(first_run_id)
        second_run = repository.get(second_run_id)
        task_service = TaskService(
            TaskRepository(session),
            _audit(tmp_path),
        )
        first_task = task_service.get(first_task_id)
        second_task = task_service.get(second_task_id)

    audit_text = (tmp_path / "worker-audit.jsonl").read_text()
    assert first_run.status is AsyncRunStatus.FAILED
    assert first_run.last_error_code == "invalid_response_contract"
    assert secret not in (first_run.last_error_message or "")
    assert first_run.checkpoint_json is not None
    assert '"stage":"terminal"' in first_run.checkpoint_json
    assert first_run.notification_status.value == "pending"
    assert first_task.status is TaskStatus.FAILED
    assert second_run.status is AsyncRunStatus.COMPLETED
    assert second_task.status is TaskStatus.COMPLETED
    assert "async_run.failed" in audit_text
    assert secret not in audit_text


@pytest.mark.asyncio
async def test_worker_replans_safe_truth_drift_before_execution(
    session_factory: sessionmaker[Session],
    tmp_path: Path,
) -> None:
    from app.db.models import WorkflowRow

    (tmp_path / "workspace").mkdir()
    task_id, run_id = _seed_run(
        session_factory,
        tmp_path,
        key="safe-replan",
    )
    with session_factory() as session:
        project = session.get(ProjectRow, "proj_safe-replan")
        assert project is not None
        project.current_phase = "L5-08-runtime"
        project.constraints = ["runtime truth changed"]
        project.version += 1
        session.commit()

    executor = SequenceExecutor(
        [OpenClawExecutionResult(outcome="completed", summary="done")]
    )
    worker = _worker(
        session_factory=session_factory,
        tmp_path=tmp_path,
        executor=executor,
        clock=[NOW],
    )

    processed = await worker.run_once()

    with session_factory() as session:
        workflow = session.get(WorkflowRow, run_id)
        run = AsyncTaskRepository(session).get(run_id)

    assert processed is True
    assert executor.requests
    assert run.status is AsyncRunStatus.COMPLETED
    assert workflow is not None
    assert workflow.plan_payload["revision"] == 2
    assert workflow.plan_payload["replanned_from_revision"] == 1
    assert workflow.plan_payload["truth"]["current_phase"] == "L5-08-runtime"
    project_constraints = [
        item["description"]
        for item in workflow.plan_payload["constraints"]
        if item["source"] == "project"
    ]
    assert project_constraints == ["runtime truth changed"]


@pytest.mark.asyncio
async def test_worker_blocks_paused_project_before_executor(
    session_factory: sessionmaker[Session],
    tmp_path: Path,
) -> None:
    (tmp_path / "workspace").mkdir()
    task_id, run_id = _seed_run(
        session_factory,
        tmp_path,
        key="paused-replan",
    )
    with session_factory() as session:
        project = session.get(ProjectRow, "proj_paused-replan")
        assert project is not None
        project.status = "paused"
        project.version += 1
        session.commit()

    executor = SequenceExecutor(
        [OpenClawExecutionResult(outcome="completed", summary="must not run")]
    )
    worker = _worker(
        session_factory=session_factory,
        tmp_path=tmp_path,
        executor=executor,
        clock=[NOW],
    )

    processed = await worker.run_once()

    with session_factory() as session:
        run = AsyncTaskRepository(session).get(run_id)
        task = TaskService(TaskRepository(session), _audit(tmp_path)).get(task_id)

    assert processed is True
    assert executor.requests == []
    assert run.status is AsyncRunStatus.BLOCKED
    assert run.last_error_code == "replan_blocked"
    assert task.status is TaskStatus.BLOCKED


@pytest.mark.asyncio
async def test_worker_blocks_when_planned_workspace_disappears(
    session_factory: sessionmaker[Session],
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    task_id, run_id = _seed_run(
        session_factory,
        tmp_path,
        key="workspace-disappeared",
    )
    workspace.rmdir()

    executor = SequenceExecutor(
        [OpenClawExecutionResult(outcome="completed", summary="must not run")]
    )
    worker = _worker(
        session_factory=session_factory,
        tmp_path=tmp_path,
        executor=executor,
        clock=[NOW],
    )

    processed = await worker.run_once()

    with session_factory() as session:
        run = AsyncTaskRepository(session).get(run_id)

    assert processed is True
    assert executor.requests == []
    assert run.status is AsyncRunStatus.BLOCKED
    assert run.last_error_code == "replan_blocked"
    assert "workspace" in (run.last_error_message or "").lower()


@pytest.mark.asyncio
async def test_worker_blocks_truth_drift_on_retry_before_second_execution(
    session_factory: sessionmaker[Session],
    tmp_path: Path,
) -> None:
    from app.db.models import AsyncTaskRunRow

    (tmp_path / "workspace").mkdir()
    task_id, run_id = _seed_run(
        session_factory,
        tmp_path,
        key="retry-drift",
    )
    with session_factory() as session:
        run_row = session.get(AsyncTaskRunRow, run_id)
        project = session.get(ProjectRow, "proj_retry-drift")
        assert run_row is not None
        assert project is not None
        run_row.status = AsyncRunStatus.RETRY_WAIT.value
        run_row.attempt = 1
        run_row.checkpoint_json = json.dumps(
            {"stage": "running", "message": "attempt one started"}
        )
        project.current_phase = "changed-after-attempt"
        project.version += 1
        session.commit()

    executor = SequenceExecutor(
        [OpenClawExecutionResult(outcome="completed", summary="must not run")]
    )
    worker = _worker(
        session_factory=session_factory,
        tmp_path=tmp_path,
        executor=executor,
        clock=[NOW],
    )

    processed = await worker.run_once()

    with session_factory() as session:
        run = AsyncTaskRepository(session).get(run_id)

    assert processed is True
    assert executor.requests == []
    assert run.status is AsyncRunStatus.BLOCKED
    assert run.attempt == 2
    assert run.last_error_code == "replan_blocked"
    assert "execution" in (run.last_error_message or "").lower()


@pytest.mark.asyncio
async def test_worker_keeps_legacy_run_without_durable_plan_compatible(
    session_factory: sessionmaker[Session],
    tmp_path: Path,
) -> None:
    from app.db.models import WorkflowRow

    (tmp_path / "workspace").mkdir()
    task_id, run_id = _seed_run(
        session_factory,
        tmp_path,
        key="legacy-no-plan",
    )
    with session_factory() as session:
        workflow = session.get(WorkflowRow, run_id)
        assert workflow is not None
        workflow.plan_payload = {}
        session.commit()

    executor = SequenceExecutor(
        [OpenClawExecutionResult(outcome="completed", summary="legacy ok")]
    )
    worker = _worker(
        session_factory=session_factory,
        tmp_path=tmp_path,
        executor=executor,
        clock=[NOW],
    )

    assert await worker.run_once() is True
    assert executor.requests
    with session_factory() as session:
        run = AsyncTaskRepository(session).get(run_id)
    assert run.status is AsyncRunStatus.COMPLETED


@pytest.mark.asyncio
async def test_worker_blocks_corrupt_persisted_plan_before_executor(
    session_factory: sessionmaker[Session],
    tmp_path: Path,
) -> None:
    from app.db.models import WorkflowRow

    (tmp_path / "workspace").mkdir()
    task_id, run_id = _seed_run(
        session_factory,
        tmp_path,
        key="corrupt-plan",
    )
    with session_factory() as session:
        workflow = session.get(WorkflowRow, run_id)
        assert workflow is not None
        workflow.plan_payload = {"id": "corrupt-plan"}
        session.commit()

    executor = SequenceExecutor(
        [OpenClawExecutionResult(outcome="completed", summary="must not run")]
    )
    worker = _worker(
        session_factory=session_factory,
        tmp_path=tmp_path,
        executor=executor,
        clock=[NOW],
    )

    processed = await worker.run_once()

    with session_factory() as session:
        run = AsyncTaskRepository(session).get(run_id)
        task = TaskService(TaskRepository(session), _audit(tmp_path)).get(task_id)

    assert processed is True
    assert executor.requests == []
    assert run.status is AsyncRunStatus.BLOCKED
    assert run.last_error_code == "replan_plan_invalid"
    assert task.status is TaskStatus.BLOCKED


@pytest.mark.asyncio
async def test_worker_natural_health_ready_uses_local_readonly_probe(
    session_factory: sessionmaker[Session],
    tmp_path: Path,
) -> None:
    task_id, run_id = _seed_run(
        session_factory,
        tmp_path,
        key="natural-core-health-ready",
        goal=(
            "Kiểm tra giúp anh trạng thái hiện tại của Ánh Dương Core. "
            "Nếu hệ thống đang ổn thì báo ngắn gọn health, ready và kết "
            "luận có thể tiếp tục làm việc hay không. Chỉ kiểm tra "
            "read-only, không sửa file, không restart service, không đổi "
            "cấu hình."
        ),
    )
    executor = SequenceExecutor(
        [OpenClawExecutionResult(outcome="completed", summary="unexpected")]
    )

    async def core_status_probe() -> dict[str, object]:
        return {
            "health": {"http_status": 200, "status": "ok"},
            "ready": {"http_status": 200, "status": "ready"},
        }

    worker = _worker(
        session_factory=session_factory,
        tmp_path=tmp_path,
        executor=executor,
        clock=[NOW],
        core_status_probe=core_status_probe,
    )
    processed = await worker.run_once()

    with session_factory() as session:
        run = AsyncTaskRepository(session).get(run_id)
        task = TaskService(TaskRepository(session), _audit(tmp_path)).get(task_id)

    assert processed is True
    assert executor.requests == []
    assert run.status is AsyncRunStatus.COMPLETED
    assert task.status is TaskStatus.COMPLETED
    result_json = json.loads(run.result_json or "{}")
    assert result_json["artifacts"]["health"]["status"] == "ok"
    assert result_json["artifacts"]["ready"]["status"] == "ready"
    assert result_json["commands_run"] == []
    assert result_json["files_changed"] == []


@pytest.mark.asyncio
async def test_worker_exact_multiline_readonly_prompt_never_calls_openclaw(
    session_factory: sessionmaker[Session],
    tmp_path: Path,
) -> None:
    goal = (
        "Kiểm tra trạng thái hệ thống hiện tại bằng chế độ chỉ đọc.\n\n"
        "Yêu cầu:\n"
        "Core tự kiểm tra /health và /ready.\n"
        "Không gọi OpenClaw hoặc model.\n"
        "Không chạy Git.\n"
        "Không sửa file hoặc config.\n"
        "Không restart service.\n"
        "Không install, deploy hoặc thay đổi hệ thống.\n"
        "Chỉ trả về kết quả health/ready thực tế và kết luận hệ thống có "
        "đang sẵn sàng hay không."
    )
    task_id, run_id = _seed_run(
        session_factory,
        tmp_path,
        key="ad-bug-readonly-exact",
        goal=goal,
    )
    executor = SequenceExecutor([])

    async def core_status_probe() -> dict[str, object]:
        return {
            "health": {"http_status": 200, "status": "ok"},
            "ready": {"http_status": 200, "status": "ready"},
        }

    worker = _worker(
        session_factory=session_factory,
        tmp_path=tmp_path,
        executor=executor,
        clock=[NOW],
        core_status_probe=core_status_probe,
    )

    processed = await worker.run_once()

    with session_factory() as session:
        run = AsyncTaskRepository(session).get(run_id)
        task = TaskService(TaskRepository(session), _audit(tmp_path)).get(task_id)

    assert processed is True
    assert executor.requests == []
    assert run.status is AsyncRunStatus.COMPLETED
    assert run.external_run_id is None
    assert task.status is TaskStatus.COMPLETED
    result_json = json.loads(run.result_json or "{}")
    assert result_json["commands_run"] == []
    assert result_json["files_changed"] == []
    assert result_json["artifacts"]["health"]["http_status"] == 200
    assert result_json["artifacts"]["ready"]["http_status"] == 200
