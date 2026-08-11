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
    AsyncTaskRepository,
)
from app.audit import AuditWriter
from app.db.base import Base
from app.db.models import ProjectRow, TaskRow
from app.db.session import create_db_engine
from app.tasks import TaskPriority, TaskStatus

NOW = datetime(2026, 7, 28, 8, 0, tzinfo=UTC)
RAW_BEARER = "audit-bearer-secret-123"
RAW_API_KEY = "audit-api-key-secret-456"


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    runtime_engine = create_db_engine(
        "sqlite+pysqlite:///"
        f"{tmp_path / 'async-audit.db'}"
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


def _seed_run(
    session: Session,
    repository: AsyncTaskRepository,
    *,
    suffix: str,
) -> str:
    project = ProjectRow(
        id=f"proj_audit_{suffix}",
        name=f"Audit Project {suffix}",
        slug=f"audit-project-{suffix}",
        status="active",
    )
    task = TaskRow(
        id=f"task_audit_{suffix}",
        project_id=project.id,
        title="Audit lifecycle",
        description="Audit lifecycle",
        status=TaskStatus.QUEUED.value,
        priority=TaskPriority.NORMAL.value,
        risk_level=0,
        requested_by="audit-test",
        source_channel="api",
        approval_required=False,
    )
    session.add_all((project, task))
    session.flush()
    run = repository.enqueue(
        task_id=task.id,
        request=AsyncTaskCreate(
            project_id=project.id,
            title="Audit lifecycle",
            goal=f"Use Bearer {RAW_BEARER}",
            constraints=(f"api_key={RAW_API_KEY}",),
            source_channel="api",
            requested_by="audit-test",
        ),
        idempotency_key=f"audit:{suffix}",
        now=NOW,
    )
    return run.id


def _records(path: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
    ]


def test_async_run_lifecycle_audit_is_append_only_and_redacted(
    session_factory: sessionmaker[Session],
    tmp_path: Path,
) -> None:
    audit_path = tmp_path / "async-events.jsonl"
    writer = AuditWriter(audit_path, fsync=False)

    with session_factory() as session:
        repository = AsyncTaskRepository(
            session,
            audit_writer=writer,
        )

        completed_id = _seed_run(
            session,
            repository,
            suffix="completed",
        )
        claimed = repository.claim_next(
            worker_id="audit-worker",
            now=NOW,
            lease_seconds=60,
        )
        assert claimed is not None
        repository.transition(
            completed_id,
            AsyncRunStatus.RUNNING,
            now=NOW,
        )
        repository.schedule_retry(
            completed_id,
            now=NOW,
            delay_seconds=5,
            error_code="temporary",
            error_message=f"Bearer {RAW_BEARER}",
        )
        claimed = repository.claim_next(
            worker_id="audit-worker",
            now=NOW + timedelta(seconds=5),
            lease_seconds=60,
        )
        assert claimed is not None
        repository.transition(
            completed_id,
            AsyncRunStatus.RUNNING,
            now=NOW + timedelta(seconds=5),
        )
        repository.transition(
            completed_id,
            AsyncRunStatus.VERIFYING,
            now=NOW + timedelta(seconds=5),
        )
        repository.transition(
            completed_id,
            AsyncRunStatus.COMPLETED,
            now=NOW + timedelta(seconds=5),
        )

        failed_id = _seed_run(
            session,
            repository,
            suffix="failed",
        )
        claimed = repository.claim_next(
            worker_id="audit-worker",
            now=NOW,
            lease_seconds=60,
        )
        assert claimed is not None
        repository.transition(
            failed_id,
            AsyncRunStatus.RUNNING,
            now=NOW,
        )
        repository.transition(
            failed_id,
            AsyncRunStatus.FAILED,
            now=NOW,
            error_code="fatal",
            error_message=f"api_key={RAW_API_KEY}",
        )

        blocked_id = _seed_run(
            session,
            repository,
            suffix="blocked",
        )
        claimed = repository.claim_next(
            worker_id="audit-worker",
            now=NOW,
            lease_seconds=60,
        )
        assert claimed is not None
        repository.transition(
            blocked_id,
            AsyncRunStatus.BLOCKED,
            now=NOW,
            error_code="policy_block",
            error_message=f"Bearer {RAW_BEARER}",
        )

        cancelled_id = _seed_run(
            session,
            repository,
            suffix="cancelled",
        )
        repository.cancel(cancelled_id, now=NOW)
        session.commit()

    raw_audit = audit_path.read_text(encoding="utf-8")
    assert RAW_BEARER not in raw_audit
    assert RAW_API_KEY not in raw_audit
    assert "[REDACTED]" in raw_audit

    records = _records(audit_path)
    event_types = {
        str(record["event_type"]) for record in records
    }
    assert {
        "async_run.created",
        "async_run.claimed",
        "async_run.retry_scheduled",
        "async_run.completed",
        "async_run.failed",
        "async_run.blocked",
        "async_run.cancelled",
    } <= event_types
    for record in records:
        payload = record["payload"]
        assert isinstance(payload, dict)
        assert not {
            "goal",
            "request",
            "request_json",
            "authorization",
            "token",
        }.intersection(payload)

    integrity = writer.verify_integrity()
    assert integrity.valid is True
    assert integrity.line_count == len(records)
