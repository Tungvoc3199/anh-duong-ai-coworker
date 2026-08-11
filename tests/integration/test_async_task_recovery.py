from __future__ import annotations

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
    recover_stale_runs,
)
from app.audit import AuditWriter
from app.db.base import Base
from app.db.models import ProjectRow, TaskRow
from app.db.session import create_db_engine
from app.tasks import TaskPriority, TaskStatus

NOW = datetime(2026, 7, 27, 21, 0, tzinfo=UTC)


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    database_url = (
        "sqlite+pysqlite:///"
        f"{tmp_path / 'async-recovery.db'}"
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


def _seed_stale(
    session: Session,
    *,
    suffix: str,
    risk_level: int,
    uncertain: bool,
) -> tuple[str, str]:
    project = ProjectRow(
        id=f"proj_{suffix}",
        name=f"Project {suffix}",
        slug=f"project-{suffix}",
        status="active",
    )
    task = TaskRow(
        id=f"task_{suffix}",
        project_id=project.id,
        title="Recovery test",
        description="Recovery test",
        status=TaskStatus.RUNNING.value,
        priority=TaskPriority.NORMAL.value,
        risk_level=risk_level,
        requested_by="test",
        source_channel="api",
        approval_required=False,
    )
    session.add_all((project, task))
    session.flush()

    repository = AsyncTaskRepository(session)
    run = repository.enqueue(
        task_id=task.id,
        request=AsyncTaskCreate(
            project_id=project.id,
            title="Recovery test",
            goal="Recover this stale run",
            risk_level=risk_level,
            workspace="/mnt/f/AIOS/anh-duong-core",
            source_channel="api",
        ),
        idempotency_key=f"api:{suffix}",
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
        checkpoint_json=(
            '{"uncertain_side_effect":true}'
            if uncertain
            else '{"uncertain_side_effect":false}'
        ),
    )
    return task.id, run.id


def _seed_blocked_approval_run(
    session: Session,
    *,
    suffix: str,
    request_risk_level: int = 2,
    request_approval_required: bool = True,
) -> tuple[str, str]:
    project = ProjectRow(
        id=f"proj_blocked_{suffix}",
        name=f"Blocked Project {suffix}",
        slug=f"blocked-project-{suffix}",
        status="active",
    )
    task = TaskRow(
        id=f"task_blocked_{suffix}",
        project_id=project.id,
        title="Blocked recovery test",
        description="Blocked recovery test",
        status=TaskStatus.BLOCKED.value,
        priority=TaskPriority.NORMAL.value,
        risk_level=2,
        requested_by="test",
        source_channel="telegram",
        approval_required=True,
    )
    session.add_all((project, task))
    session.flush()

    run = AsyncTaskRepository(session).enqueue(
        task_id=task.id,
        request=AsyncTaskCreate(
            project_id=project.id,
            title="Blocked recovery test",
            goal="Research public Facebook posts, summarize, stop before publish.",
            risk_level=request_risk_level,
            approval_required=request_approval_required,
            workspace="/mnt/f/AIOS/anh-duong-core",
            source_channel="telegram",
            source_chat_id="chat-test",
            idempotency_key=f"telegram:blocked:{suffix}",
        ),
        idempotency_key=f"telegram:blocked:{suffix}",
        status=AsyncRunStatus.BLOCKED,
        error_code="approval_required",
        error_message=(
            "This action requires approval and is blocked "
            "in Async Task Runner v1."
        ),
        now=NOW,
    )
    return task.id, run.id


@pytest.mark.parametrize(
    ("risk_level", "uncertain", "expected_status"),
    (
        (0, False, AsyncRunStatus.PENDING),
        (1, False, AsyncRunStatus.PENDING),
        (1, True, AsyncRunStatus.BLOCKED),
        (2, False, AsyncRunStatus.BLOCKED),
    ),
)
def test_stale_recovery_is_risk_and_uncertainty_aware(
    session_factory: sessionmaker[Session],
    tmp_path: Path,
    risk_level: int,
    uncertain: bool,
    expected_status: AsyncRunStatus,
) -> None:
    suffix = f"{risk_level}-{uncertain}"
    with session_factory() as session:
        task_id, run_id = _seed_stale(
            session,
            suffix=suffix,
            risk_level=risk_level,
            uncertain=uncertain,
        )
        session.commit()

    summary = recover_stale_runs(
        session_factory,
        now=NOW,
        audit_writer=AuditWriter(
            tmp_path / "recovery-audit.jsonl",
            fsync=False,
        ),
    )

    with session_factory() as session:
        run = AsyncTaskRepository(session).get(run_id)
        task = session.get(TaskRow, task_id)

    assert run.status is expected_status
    assert run.lease_owner is None
    assert run.lease_expires_at is None
    assert summary.requeued == int(
        expected_status is AsyncRunStatus.PENDING
    )
    assert summary.blocked == int(
        expected_status is AsyncRunStatus.BLOCKED
    )
    assert task is not None
    if expected_status is AsyncRunStatus.BLOCKED:
        assert task.status == TaskStatus.BLOCKED.value


def test_recovery_requeues_legacy_approval_blocked_runs_when_policy_allows(
    session_factory: sessionmaker[Session],
    tmp_path: Path,
) -> None:
    with session_factory() as session:
        task_id, run_id = _seed_blocked_approval_run(
            session,
            suffix="approval",
        )
        session.commit()

    summary = recover_stale_runs(
        session_factory,
        now=NOW,
        audit_writer=AuditWriter(
            tmp_path / "approval-recovery-audit.jsonl",
            fsync=False,
        ),
        policy_gate=AsyncTaskPolicyGate((Path("/mnt/f/AIOS"),)),
    )

    with session_factory() as session:
        run = AsyncTaskRepository(session).get(run_id)
        task = session.get(TaskRow, task_id)

    assert summary.policy_unblocked == 1
    assert run.status is AsyncRunStatus.PENDING
    assert run.last_error_code is None
    assert run.last_error_message is None
    assert run.notification_status is not None
    assert task is not None
    assert task.status == TaskStatus.QUEUED.value


def test_recovery_does_not_requeue_inconsistent_plain_allowed_blocked_run(
    session_factory: sessionmaker[Session],
    tmp_path: Path,
) -> None:
    with session_factory() as session:
        task_id, run_id = _seed_blocked_approval_run(
            session,
            suffix="plain-allowed",
            request_risk_level=0,
            request_approval_required=False,
        )
        session.commit()

    summary = recover_stale_runs(
        session_factory,
        now=NOW,
        audit_writer=AuditWriter(
            tmp_path / "plain-allowed-recovery-audit.jsonl",
            fsync=False,
        ),
        policy_gate=AsyncTaskPolicyGate((Path("/mnt/f/AIOS"),)),
    )

    with session_factory() as session:
        run = AsyncTaskRepository(session).get(run_id)
        task = session.get(TaskRow, task_id)

    assert summary.policy_unblocked == 0
    assert run.status is AsyncRunStatus.BLOCKED
    assert run.last_error_code == "approval_required"
    assert task is not None
    assert task.status == TaskStatus.BLOCKED.value
