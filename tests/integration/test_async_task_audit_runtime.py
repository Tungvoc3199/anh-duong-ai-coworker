from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

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
    NotificationStatus,
    NotificationWorker,
    recover_stale_runs,
)
from app.audit import AuditWriter
from app.db.base import Base
from app.db.models import AsyncTaskRunRow, ProjectRow, TaskRow
from app.db.session import create_db_engine
from app.openclaw import (
    OpenClawExecutionRequest,
    OpenClawExecutionResult,
    OpenClawTransportError,
)
from app.tasks import (
    TaskCreate,
    TaskPriority,
    TaskRepository,
    TaskService,
    TaskStatus,
)

NOW = datetime.now(UTC) + timedelta(hours=1)
RAW_NOTIFICATION_SECRET = "notification-secret-789"


class CompleteExecutor:
    async def execute(
        self,
        _request: OpenClawExecutionRequest,
    ) -> OpenClawExecutionResult:
        return OpenClawExecutionResult(
            outcome="completed",
            summary="Completed by mock HTTP executor.",
            external_run_id="mock-response",
        )


class SuccessfulNotifier:
    async def send_final(self, _run: object) -> None:
        return None


class FailedNotifier:
    async def send_final(self, _run: object) -> None:
        raise OpenClawTransportError(
            "notification_rejected",
            f"Bearer {RAW_NOTIFICATION_SECRET}",
            retryable=False,
        )


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    runtime_engine = create_db_engine(
        "sqlite+pysqlite:///"
        f"{tmp_path / 'async-audit-runtime.db'}"
    )
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


def _event_types(path: Path) -> set[str]:
    return {
        str(json.loads(line)["event_type"])
        for line in path.read_text(encoding="utf-8").splitlines()
    }


def _create_project(session: Session, suffix: str) -> ProjectRow:
    project = ProjectRow(
        id=f"proj_runtime_audit_{suffix}",
        name=f"Runtime Audit {suffix}",
        slug=f"runtime-audit-{suffix}",
        status="active",
    )
    session.add(project)
    session.flush()
    return project


@pytest.mark.asyncio
async def test_worker_writes_claimed_and_completed_audit_events(
    session_factory: sessionmaker[Session],
    tmp_path: Path,
) -> None:
    audit_path = tmp_path / "worker-runtime-audit.jsonl"
    writer = AuditWriter(audit_path, fsync=False)
    with session_factory() as session:
        project = _create_project(session, "worker")
        service = AsyncTaskService(
            task_service=TaskService(
                TaskRepository(session),
                writer,
            ),
            repository=AsyncTaskRepository(
                session,
                audit_writer=writer,
            ),
            policy_gate=AsyncTaskPolicyGate((tmp_path,)),
        )
        service.create(
            AsyncTaskCreate(
                project_id=project.id,
                title="Runtime audit worker",
                goal="Complete through mocked HTTP.",
                workspace=str(tmp_path),
                idempotency_key="runtime-audit-worker",
            )
        )
        session.commit()

    worker = AsyncTaskWorker(
        session_factory=session_factory,
        audit_writer=writer,
        policy_gate=AsyncTaskPolicyGate((tmp_path,)),
        executor=CompleteExecutor(),
        worker_id="runtime-audit-worker",
        lease_seconds=60,
        clock=lambda: NOW,
    )
    assert await worker.run_once() is True

    assert {
        "async_run.created",
        "async_run.claimed",
        "async_run.completed",
    } <= _event_types(audit_path)


def test_stale_recovery_writes_recovered_and_blocked_events(
    session_factory: sessionmaker[Session],
    tmp_path: Path,
) -> None:
    audit_path = tmp_path / "recovery-runtime-audit.jsonl"
    writer = AuditWriter(audit_path, fsync=False)
    with session_factory() as session:
        project = _create_project(session, "recovery")
        task = TaskService(
            TaskRepository(session),
            writer,
        ).create(
            TaskCreate(
                project_id=project.id,
                title="Stale recovery audit",
                description="Stale recovery audit",
                risk_level=2,
            )
        )
        repository = AsyncTaskRepository(session)
        run = repository.enqueue(
            task_id=task.id,
            request=AsyncTaskCreate(
                project_id=project.id,
                title="Stale recovery audit",
                goal="Do not replay an unsafe stale run.",
                risk_level=2,
                workspace=str(tmp_path),
            ),
            idempotency_key="runtime-audit-recovery",
            now=NOW - timedelta(hours=1),
        )
        claimed = repository.claim_next(
            worker_id="dead-worker",
            now=NOW - timedelta(hours=1),
            lease_seconds=30,
        )
        assert claimed is not None
        repository.transition(
            run.id,
            AsyncRunStatus.RUNNING,
            now=NOW - timedelta(hours=1),
            checkpoint_json='{"uncertain_side_effect":true}',
        )
        session.commit()

    summary = recover_stale_runs(
        session_factory,
        now=NOW,
        audit_writer=writer,
    )

    assert summary.blocked == 1
    assert {
        "async_run.recovered",
        "async_run.blocked",
    } <= _event_types(audit_path)


def _seed_notification(
    session_factory: sessionmaker[Session],
    *,
    suffix: str,
) -> str:
    with session_factory() as session:
        project = _create_project(session, suffix)
        task = TaskRow(
            id=f"task_runtime_audit_{suffix}",
            project_id=project.id,
            title="Notification audit",
            description="Notification audit",
            status=TaskStatus.COMPLETED.value,
            priority=TaskPriority.NORMAL.value,
            risk_level=0,
            requested_by="test",
            source_channel="telegram",
            approval_required=False,
        )
        session.add(task)
        session.flush()
        repository = AsyncTaskRepository(session)
        run = repository.enqueue(
            task_id=task.id,
            request=AsyncTaskCreate(
                project_id=project.id,
                title="Notification audit",
                goal="Send final notification through HTTP.",
                source_channel="telegram",
                source_chat_id="chat-test",
                idempotency_key=f"runtime-audit-{suffix}",
            ),
            idempotency_key=f"runtime-audit-{suffix}",
            now=NOW,
        )
        row = session.get(AsyncTaskRunRow, run.id)
        assert row is not None
        row.status = AsyncRunStatus.COMPLETED.value
        row.notification_status = NotificationStatus.PENDING.value
        session.commit()
        return run.id


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("suffix", "notifier", "expected_event"),
    (
        (
            "notify-success",
            SuccessfulNotifier(),
            "async_notification.sent",
        ),
        (
            "notify-failed",
            FailedNotifier(),
            "async_notification.failed",
        ),
    ),
)
async def test_notification_terminal_status_is_audited(
    session_factory: sessionmaker[Session],
    tmp_path: Path,
    suffix: str,
    notifier: object,
    expected_event: str,
) -> None:
    _seed_notification(session_factory, suffix=suffix)
    audit_path = tmp_path / f"{suffix}.jsonl"
    writer = AuditWriter(audit_path, fsync=False)
    worker = NotificationWorker(
        session_factory=session_factory,
        notifier=notifier,  # type: ignore[arg-type]
        audit_writer=writer,
        clock=lambda: NOW,
    )

    assert await worker.run_once() is True

    raw_audit = audit_path.read_text(encoding="utf-8")
    assert RAW_NOTIFICATION_SECRET not in raw_audit
    assert expected_event in _event_types(audit_path)
