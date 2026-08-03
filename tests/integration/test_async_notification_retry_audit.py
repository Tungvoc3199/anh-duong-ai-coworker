from __future__ import annotations

import json
from collections.abc import Iterator, Sequence
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.async_tasks import (
    AsyncRunStatus,
    AsyncTaskCreate,
    AsyncTaskRepository,
    NotificationStatus,
    NotificationWorker,
)
from app.audit import AuditWriter
from app.db.base import Base
from app.db.models import AsyncTaskRunRow, ProjectRow, TaskRow
from app.db.session import create_db_engine
from app.openclaw import OpenClawTransportError
from app.tasks import TaskPriority, TaskStatus

NOW = datetime(2026, 7, 28, 11, 0, tzinfo=UTC)
RAW_SECRET = "notification-retry-secret-123"


class SequenceNotifier:
    def __init__(self, outcomes: Sequence[Exception | None]) -> None:
        self.outcomes = list(outcomes)

    async def send_final(self, _run: object) -> None:
        outcome = self.outcomes.pop(0)
        if outcome is not None:
            raise outcome


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    runtime_engine = create_db_engine(
        "sqlite+pysqlite:///"
        f"{tmp_path / 'notification-retry-audit.db'}"
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


def _seed_pending(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        project = ProjectRow(
            id="proj_notification_retry_audit",
            name="Notification Retry Audit",
            slug="notification-retry-audit",
            status="active",
        )
        task = TaskRow(
            id="task_notification_retry_audit",
            project_id=project.id,
            title="Notification retry audit",
            description="Notification retry audit",
            status=TaskStatus.COMPLETED.value,
            priority=TaskPriority.NORMAL.value,
            risk_level=0,
            requested_by="test",
            source_channel="telegram",
            approval_required=False,
        )
        session.add_all((project, task))
        session.flush()
        run = AsyncTaskRepository(session).enqueue(
            task_id=task.id,
            request=AsyncTaskCreate(
                project_id=project.id,
                title="Notification retry audit",
                goal="Audit each HTTP delivery failure.",
                source_channel="telegram",
                source_chat_id="chat-test",
                idempotency_key="notification-retry-audit",
            ),
            idempotency_key="notification-retry-audit",
            now=NOW,
        )
        row = session.get(AsyncTaskRunRow, run.id)
        assert row is not None
        row.status = AsyncRunStatus.COMPLETED.value
        row.notification_status = NotificationStatus.PENDING.value
        session.commit()


@pytest.mark.asyncio
async def test_each_failed_notification_attempt_is_audited(
    session_factory: sessionmaker[Session],
    tmp_path: Path,
) -> None:
    _seed_pending(session_factory)
    error = OpenClawTransportError(
        "gateway_unavailable",
        f"Bearer {RAW_SECRET}",
        retryable=True,
    )
    audit_path = tmp_path / "notification-retry-audit.jsonl"
    worker = NotificationWorker(
        session_factory=session_factory,
        notifier=SequenceNotifier((error, error, None)),
        audit_writer=AuditWriter(audit_path, fsync=False),
        clock=lambda: NOW,
    )

    assert await worker.run_once() is True
    assert await worker.run_once() is True
    assert await worker.run_once() is True

    raw_audit = audit_path.read_text(encoding="utf-8")
    records = [
        json.loads(line) for line in raw_audit.splitlines()
    ]
    event_types = [
        record["event_type"] for record in records
    ]
    assert event_types.count("async_notification.failed") == 2
    assert event_types.count("async_notification.sent") == 1
    assert RAW_SECRET not in raw_audit
