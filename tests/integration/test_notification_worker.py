from __future__ import annotations

from collections.abc import Iterator, Sequence
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.async_tasks import (
    AsyncRunStatus,
    AsyncTaskCreate,
    AsyncTaskMode,
    AsyncTaskRepository,
    NotificationStatus,
    NotificationWorker,
)
from app.db.base import Base
from app.db.models import AsyncTaskRunRow, ProjectRow, TaskRow
from app.db.session import create_db_engine
from app.openclaw import OpenClawTransportError
from app.tasks import TaskPriority, TaskStatus

NOW = datetime(2026, 7, 27, 23, 0, tzinfo=UTC)


class SequenceNotifier:
    def __init__(self, outcomes: Sequence[Exception | None]) -> None:
        self.outcomes = list(outcomes)
        self.calls = 0
        self.runs: list[object] = []

    async def send_final(self, run: object) -> None:
        self.calls += 1
        self.runs.append(run)
        outcome = self.outcomes.pop(0)
        if outcome is not None:
            raise outcome


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    runtime_engine = create_db_engine(
        "sqlite+pysqlite:///"
        f"{tmp_path / 'notification-worker.db'}"
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


def _seed_pending_notification(
    session_factory: sessionmaker[Session],
) -> tuple[str, str]:
    with session_factory() as session:
        project = ProjectRow(
            id="proj_notify",
            name="Notify Project",
            slug="notify-project",
            status="active",
        )
        task = TaskRow(
            id="task_notify",
            project_id=project.id,
            title="Notify",
            description="Notify",
            status=TaskStatus.COMPLETED.value,
            priority=TaskPriority.NORMAL.value,
            risk_level=0,
            requested_by="test",
            source_channel="telegram",
            approval_required=False,
            result_summary="Done",
        )
        session.add_all((project, task))
        session.flush()
        repository = AsyncTaskRepository(session)
        run = repository.enqueue(
            task_id=task.id,
            request=AsyncTaskCreate(
                project_id=project.id,
                title="Notify",
                goal="Notify final result",
                mode=AsyncTaskMode.QUICK,
                source_channel="telegram",
                source_chat_id="chat-test",
                idempotency_key="telegram:notify",
            ),
            idempotency_key="telegram:notify",
            now=NOW,
        )
        run_row = session.get(AsyncTaskRunRow, run.id)
        assert run_row is not None
        run_row.status = AsyncRunStatus.COMPLETED.value
        run_row.result_json = (
            '{"outcome":"completed","summary":"Done"}'
        )
        run_row.notification_status = (
            NotificationStatus.PENDING.value
        )
        session.commit()
        return task.id, run.id


@pytest.mark.asyncio
async def test_notification_worker_marks_success_sent(
    session_factory: sessionmaker[Session],
) -> None:
    _task_id, run_id = _seed_pending_notification(
        session_factory
    )
    notifier = SequenceNotifier([None])
    worker = NotificationWorker(
        session_factory=session_factory,
        notifier=notifier,
        clock=lambda: NOW,
    )

    processed = await worker.run_once()

    with session_factory() as session:
        run = AsyncTaskRepository(session).get(run_id)

    assert processed is True
    assert run.notification_status is NotificationStatus.SENT
    assert run.notification_attempts == 1


@pytest.mark.asyncio
async def test_notification_fails_after_five_independent_attempts(
    session_factory: sessionmaker[Session],
) -> None:
    task_id, run_id = _seed_pending_notification(
        session_factory
    )
    errors = [
        OpenClawTransportError(
            "gateway_unavailable",
            "temporary failure",
            retryable=True,
        )
        for _ in range(5)
    ]
    worker = NotificationWorker(
        session_factory=session_factory,
        notifier=SequenceNotifier(errors),
        clock=lambda: NOW,
    )

    for _ in range(5):
        assert await worker.run_once() is True

    with session_factory() as session:
        run = AsyncTaskRepository(session).get(run_id)
        task = session.get(TaskRow, task_id)

    assert run.notification_status is NotificationStatus.FAILED
    assert run.notification_attempts == 5
    assert task is not None
    assert task.status == TaskStatus.COMPLETED.value
    assert await worker.run_once() is False


@pytest.mark.asyncio
async def test_notification_worker_sends_blocked_telegram_run(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        project = ProjectRow(
            id="proj_notify_blocked",
            name="Notify Blocked Project",
            slug="notify-blocked-project",
            status="active",
        )
        task = TaskRow(
            id="task_notify_blocked",
            project_id=project.id,
            title="Blocked",
            description="Blocked",
            status=TaskStatus.BLOCKED.value,
            priority=TaskPriority.NORMAL.value,
            risk_level=2,
            requested_by="test",
            source_channel="telegram",
            approval_required=True,
            result_summary="approval_required: blocked",
        )
        session.add_all((project, task))
        session.flush()
        repository = AsyncTaskRepository(session)
        run = repository.enqueue(
            task_id=task.id,
            request=AsyncTaskCreate(
                project_id=project.id,
                title="Blocked",
                goal="Blocked final result",
                mode=AsyncTaskMode.QUICK,
                risk_level=2,
                source_channel="telegram",
                source_chat_id="chat-test",
                idempotency_key="telegram:blocked",
            ),
            idempotency_key="telegram:blocked",
            now=NOW,
            status=AsyncRunStatus.BLOCKED,
            error_code="approval_required",
            error_message="This action requires approval.",
        )
        session.commit()

    notifier = SequenceNotifier([None])
    worker = NotificationWorker(
        session_factory=session_factory,
        notifier=notifier,
        clock=lambda: NOW,
    )

    processed = await worker.run_once()

    with session_factory() as session:
        current = AsyncTaskRepository(session).get(run.id)

    assert processed is True
    assert notifier.calls == 1
    assert notifier.runs[0].status is AsyncRunStatus.BLOCKED
    assert notifier.runs[0].last_error_code == "approval_required"
    assert "requires approval" in notifier.runs[0].last_error_message
    assert current.notification_status is NotificationStatus.SENT
