"""RED tests: governed coding bridge over the async-task seam (AD-L5-05).

Covers the Core-owned seams that carry a typed ``governed_coding`` payload:
models, service, worker gating, and the generic API rejection rule.
"""
from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from pydantic import ValidationError
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
)
from app.orchestration.coding_governance import (
    CodingAssignment,
    CodingResultContract,
    FailureClassification,
    GovernedTestEvidence,
    ReviewerOutcome,
)

NOW = datetime.now(UTC) + timedelta(hours=1)


def _assignment_dict(tmp_path: Path) -> dict[str, Any]:
    workspace = tmp_path / "anh-duong-core.worktrees" / "bridge-1"
    return {
        "checkpoint_id": "AD-L5-05",
        "correlation_id": "req_bridge_1",
        "workspace": str(workspace),
        "manifest_digest": "a" * 64,
        "allowed_paths": ["app/", "tests/"],
        "reviewer_required": True,
        "approval_required": False,
        "max_semantic_repair_rounds": 2,
    }


def _result_dict() -> dict[str, Any]:
    return {
        "checkpoint_id": "AD-L5-05",
        "correlation_id": "req_bridge_1",
        "status": "MERGE_READY",
        "classification": FailureClassification.DELTA_FAILURE.value,
        "manifest_digest": "a" * 64,
        "files_changed": ["app/example.py"],
        "commands_run": ["pytest -q"],
        "tests": [{"name": "pytest", "status": "PASS"}],
        "model": "router/model",
        "provider": "router",
        "profile": "CE-2",
        "duration_ms": 100,
        "error_code": None,
        "production_write": False,
        "service_restart": False,
        "database_write": False,
        "reviewer_outcome": ReviewerOutcome.PASS.value,
        "reviewer_read_only": True,
        "approval_granted": False,
        "repair_round": 0,
    }


# ---------------------------------------------------------------------------
# Models: typed governed_coding payload on AsyncTaskCreate
# ---------------------------------------------------------------------------

def test_async_task_create_accepts_typed_governed_coding(
    tmp_path: Path,
) -> None:
    request = AsyncTaskCreate(
        project_id="proj_bridge",
        title="Governed coding run",
        goal="Implement the governed coding bridge.",
        mode="build",
        risk_level=0,
        approval_required=False,
        workspace=str(
            tmp_path / "anh-duong-core.worktrees" / "bridge-1"
        ),
        source_channel="api",
        idempotency_key="api:governed-1",
        governed_coding=_assignment_dict(tmp_path),
    )

    assert request.governed_coding is not None
    assert isinstance(request.governed_coding, CodingAssignment)
    assert request.governed_coding.checkpoint_id == "AD-L5-05"
    assert request.governed_coding.allowed_paths == ("app/", "tests/")


def test_async_task_create_rejects_invalid_governed_assignment(
    tmp_path: Path,
) -> None:
    invalid = _assignment_dict(tmp_path)
    invalid["allowed_paths"] = []

    with pytest.raises(ValidationError):
        AsyncTaskCreate(
            project_id="proj_bridge",
            title="Governed coding run",
            goal="Implement the governed coding bridge.",
            mode="build",
            workspace=str(
                tmp_path / "anh-duong-core.worktrees" / "bridge-1"
            ),
            source_channel="api",
            idempotency_key="api:governed-invalid",
            governed_coding=invalid,
        )


def test_async_task_create_rejects_production_workspace_in_assignment(
    tmp_path: Path,
) -> None:
    assignment = _assignment_dict(tmp_path)
    assignment["workspace"] = "/home/thadc/AIOS/anh-duong-core"

    with pytest.raises(ValidationError, match="isolated worktree"):
        AsyncTaskCreate(
            project_id="proj_bridge",
            title="Governed coding run",
            goal="Implement the governed coding bridge.",
            mode="build",
            workspace="/home/thadc/AIOS/anh-duong-core",
            source_channel="api",
            idempotency_key="api:governed-prod",
            governed_coding=assignment,
        )


def test_async_task_create_defaults_to_none_governed_coding() -> None:
    request = AsyncTaskCreate(
        project_id="proj_plain",
        title="Plain task",
        goal="Ordinary non-coding task.",
        mode="quick",
        source_channel="api",
    )
    assert request.governed_coding is None


def test_governed_payload_survives_request_json_round_trip(
    tmp_path: Path,
) -> None:
    request = AsyncTaskCreate(
        project_id="proj_bridge",
        title="Governed coding run",
        goal="Implement the governed coding bridge.",
        mode="build",
        workspace=str(
            tmp_path / "anh-duong-core.worktrees" / "bridge-1"
        ),
        source_channel="api",
        idempotency_key="api:governed-roundtrip",
        governed_coding=_assignment_dict(tmp_path),
    )
    restored = AsyncTaskCreate.model_validate_json(
        request.model_dump_json()
    )

    assert restored.governed_coding == request.governed_coding


# ---------------------------------------------------------------------------
# Service + repository: durable persistence of the typed payload
# ---------------------------------------------------------------------------


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    runtime_engine = create_db_engine(
        "sqlite+pysqlite:///" f"{tmp_path / 'governed-bridge.db'}"
    )
    Base.metadata.create_all(runtime_engine)
    try:
        yield runtime_engine
    finally:
        runtime_engine.dispose()


@pytest.fixture
def session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(
        bind=engine,
        class_=Session,
        expire_on_commit=False,
        autoflush=False,
    )


def _make_task_service(session: Session, tmp_path: Path) -> Any:
    from app.audit import AuditWriter as _AuditWriter
    from app.tasks import TaskRepository as _TaskRepository
    from app.tasks import TaskService as _TaskService

    return _TaskService(
        _TaskRepository(session),
        _AuditWriter(tmp_path / "persist-audit.jsonl", fsync=False),
    )


def test_service_persists_governed_assignment_in_request_json(
    session_factory: sessionmaker[Session],
    tmp_path: Path,
) -> None:
    with session_factory() as session:
        session.add(
            ProjectRow(
                id="proj_bridge",
                name="Project bridge",
                slug="project-bridge",
                status="active",
            )
        )
        session.commit()
        service = AsyncTaskService(
            task_service=_make_task_service(session, tmp_path),
            repository=AsyncTaskRepository(session),
            policy_gate=AsyncTaskPolicyGate((tmp_path,)),
        )
        accepted = service.create(
            AsyncTaskCreate(
                project_id="proj_bridge",
                title="Governed coding run",
                goal="Implement the governed coding bridge.",
                mode="build",
                workspace=str(
                    tmp_path / "anh-duong-core.worktrees" / "bridge-1"
                ),
                source_channel="api",
                idempotency_key="api:governed-persist",
                governed_coding=_assignment_dict(tmp_path),
            )
        )
        run = AsyncTaskRepository(session).get(accepted.run_id)
        session.commit()

    payload = json.loads(run.request_json)
    assert payload["governed_coding"]["checkpoint_id"] == "AD-L5-05"
    assert payload["governed_coding"]["manifest_digest"] == "a" * 64
    restored = AsyncTaskCreate.model_validate_json(run.request_json)
    assert restored.governed_coding is not None
    assert restored.governed_coding.correlation_id == "req_bridge_1"


# ---------------------------------------------------------------------------
# Worker: pre-execution validation and completion gate
# ---------------------------------------------------------------------------


class RecordingExecutor:
    def __init__(self, result: OpenClawExecutionResult) -> None:
        self.result = result
        self.requests: list[OpenClawExecutionRequest] = []

    async def execute(
        self,
        request: OpenClawExecutionRequest,
    ) -> OpenClawExecutionResult:
        self.requests.append(request)
        return self.result


def _seed_governed_run(
    session_factory: sessionmaker[Session],
    tmp_path: Path,
    *,
    key: str,
) -> tuple[str, str]:
    with session_factory() as session:
        session.add(
            ProjectRow(
                id=f"proj_{key}",
                name=f"Project {key}",
                slug=f"project-{key}",
                status="active",
            )
        )
        session.flush()
        service = AsyncTaskService(
            task_service=_make_task_service(session, tmp_path),
            repository=AsyncTaskRepository(session),
            policy_gate=AsyncTaskPolicyGate((tmp_path,)),
        )
        accepted = service.create(
            AsyncTaskCreate(
                project_id=f"proj_{key}",
                title="Governed coding run",
                goal="Implement the governed coding bridge.",
                mode="build",
                workspace=str(
                    tmp_path / "anh-duong-core.worktrees" / "bridge-1"
                ),
                source_channel="telegram",
                source_chat_id="chat-governed",
                idempotency_key=f"telegram:{key}",
                governed_coding=_assignment_dict(tmp_path),
            )
        )
        session.commit()
        return accepted.task_id, accepted.run_id


def _worker(
    *,
    session_factory: sessionmaker[Session],
    tmp_path: Path,
    executor: Any,
) -> AsyncTaskWorker:
    return AsyncTaskWorker(
        session_factory=session_factory,
        audit_writer=AuditWriter(
            tmp_path / "worker-audit.jsonl", fsync=False
        ),
        policy_gate=AsyncTaskPolicyGate((tmp_path,)),
        executor=executor,
        worker_id="worker-governed",
        lease_seconds=900,
        clock=lambda: NOW,
    )


def _worktree_workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "anh-duong-core.worktrees" / "bridge-1"
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / ".git").write_text(
        "gitdir: /home/thadc/AIOS/anh-duong-core/.git/worktrees/bridge-1\n",
        encoding="utf-8",
    )
    return workspace


async def test_worker_carries_assignment_into_execution_request(
    session_factory: sessionmaker[Session],
    tmp_path: Path,
) -> None:
    _worktree_workspace(tmp_path)
    _, run_id = _seed_governed_run(
        session_factory,
        tmp_path,
        key="carry",
    )
    executor = RecordingExecutor(
        OpenClawExecutionResult(
            outcome="completed",
            summary="Coding finished.",
        )
    )
    worker = _worker(
        session_factory=session_factory,
        tmp_path=tmp_path,
        executor=executor,
    )

    processed = await worker.run_once()

    assert processed is True
    assert len(executor.requests) == 1
    carried = executor.requests[0].governed_coding
    assert carried is not None
    assert carried.checkpoint_id == "AD-L5-05"


async def test_worker_blocks_when_assignment_workspace_is_not_worktree(
    session_factory: sessionmaker[Session],
    tmp_path: Path,
) -> None:
    # No .git worktree file: validate_workspace() must fail.
    (tmp_path / "anh-duong-core.worktrees" / "bridge-1").mkdir(
        parents=True, exist_ok=True
    )
    task_id, run_id = _seed_governed_run(
        session_factory,
        tmp_path,
        key="not-worktree",
    )
    executor = RecordingExecutor(
        OpenClawExecutionResult(outcome="completed", summary="unused")
    )
    worker = _worker(
        session_factory=session_factory,
        tmp_path=tmp_path,
        executor=executor,
    )

    processed = await worker.run_once()

    with session_factory() as session:
        run = AsyncTaskRepository(session).get(run_id)

    assert processed is True
    assert executor.requests == []
    assert run.status is AsyncRunStatus.BLOCKED
    assert run.last_error_code == "governance_contract_violation"
    assert run.notification_status.value == "pending"

    from app.tasks import TaskRepository, TaskService, TaskStatus

    with session_factory() as session:
        task = TaskService(
            TaskRepository(session),
            AuditWriter(tmp_path / "task-audit.jsonl", fsync=False),
        ).get(task_id)
    assert task.status is TaskStatus.BLOCKED


async def test_worker_blocks_completion_without_valid_ce_result_contract(
    session_factory: sessionmaker[Session],
    tmp_path: Path,
) -> None:
    _worktree_workspace(tmp_path)
    task_id, run_id = _seed_governed_run(
        session_factory,
        tmp_path,
        key="no-contract",
    )
    # Executor claims completed but supplies NO typed governance_result.
    executor = RecordingExecutor(
        OpenClawExecutionResult(
            outcome="completed",
            summary="Coding finished without governance contract.",
        )
    )
    worker = _worker(
        session_factory=session_factory,
        tmp_path=tmp_path,
        executor=executor,
    )

    processed = await worker.run_once()

    with session_factory() as session:
        run = AsyncTaskRepository(session).get(run_id)

    assert processed is True
    assert run.status is AsyncRunStatus.BLOCKED
    assert run.last_error_code == "governance_result_missing"

    from app.tasks import TaskRepository, TaskService, TaskStatus

    with session_factory() as session:
        task = TaskService(
            TaskRepository(session),
            AuditWriter(tmp_path / "task-audit.jsonl", fsync=False),
        ).get(task_id)
    assert task.status is TaskStatus.BLOCKED


async def test_worker_completes_only_on_valid_merge_ready_contract(
    session_factory: sessionmaker[Session],
    tmp_path: Path,
) -> None:
    _worktree_workspace(tmp_path)
    task_id, run_id = _seed_governed_run(
        session_factory,
        tmp_path,
        key="merge-ready",
    )
    executor = RecordingExecutor(
        OpenClawExecutionResult(
            outcome="completed",
            summary="Merge-ready coding result.",
            governance_result=CodingResultContract(**_result_dict()),
        )
    )
    worker = _worker(
        session_factory=session_factory,
        tmp_path=tmp_path,
        executor=executor,
    )
    workspace = tmp_path / "anh-duong-core.worktrees" / "bridge-1"
    evidence = GovernedTestEvidence(
        executable=str(workspace / ".venv" / "bin" / "python"),
        argv=("-m", "pytest", "tests", "-q"),
        workspace=str(workspace),
        return_code=0,
        passed=1,
    )

    with patch(
        "app.async_tasks.worker.verify_governed_tests",
        return_value=evidence,
    ):
        processed = await worker.run_once()

    with session_factory() as session:
        run = AsyncTaskRepository(session).get(run_id)

    assert processed is True
    assert run.status is AsyncRunStatus.COMPLETED

    from app.tasks import TaskRepository, TaskService, TaskStatus

    with session_factory() as session:
        task = TaskService(
            TaskRepository(session),
            AuditWriter(tmp_path / "task-audit.jsonl", fsync=False),
        ).get(task_id)
    assert task.status is TaskStatus.COMPLETED


async def test_worker_blocks_completion_failing_scope_gate(
    session_factory: sessionmaker[Session],
    tmp_path: Path,
) -> None:
    _worktree_workspace(tmp_path)
    task_id, run_id = _seed_governed_run(
        session_factory,
        tmp_path,
        key="scope-breach",
    )
    out_of_scope = _result_dict()
    out_of_scope["files_changed"] = ["README.md"]
    executor = RecordingExecutor(
        OpenClawExecutionResult(
            outcome="completed",
            summary="Out-of-scope change attempted.",
            governance_result=CodingResultContract(**out_of_scope),
        )
    )
    worker = _worker(
        session_factory=session_factory,
        tmp_path=tmp_path,
        executor=executor,
    )

    processed = await worker.run_once()

    with session_factory() as session:
        run = AsyncTaskRepository(session).get(run_id)

    assert processed is True
    assert run.status is AsyncRunStatus.BLOCKED
    assert run.last_error_code == "governance_contract_violation"

    from app.tasks import TaskRepository, TaskService, TaskStatus

    with session_factory() as session:
        task = TaskService(
            TaskRepository(session),
            AuditWriter(tmp_path / "task-audit.jsonl", fsync=False),
        ).get(task_id)
    assert task.status is TaskStatus.BLOCKED
