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

