from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.async_tasks import (
    AsyncRunStatus,
    AsyncTaskCreate,
    AsyncTaskRepository,
)
from app.db.base import Base
from app.db.models import (
    AsyncTaskRunRow,
    ProjectRow,
    TaskRow,
)
from app.db.session import create_db_engine
from app.tasks import TaskPriority, TaskStatus

NOW = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    database_url = (
        "sqlite+pysqlite:///"
        f"{tmp_path / 'async-runner-repository.db'}"
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


def _seed_task(session: Session, suffix: str = "1") -> TaskRow:
    project = ProjectRow(
        id=f"proj_{suffix}",
        name=f"Project {suffix}",
        slug=f"project-{suffix}",
        status="active",
    )
    task = TaskRow(
        id=f"task_{suffix}",
        project_id=project.id,
        title="Async test",
        description="Repository integration test",
        status=TaskStatus.QUEUED.value,
        priority=TaskPriority.NORMAL.value,
        risk_level=0,
        requested_by="test",
        source_channel="api",
        approval_required=False,
    )
    session.add_all((project, task))
    session.flush()
    return task


def _request(project_id: str) -> AsyncTaskCreate:
    return AsyncTaskCreate(
        project_id=project_id,
        title="Async test",
        goal="Run an asynchronous test",
        source_channel="api",
        risk_level=0,
    )


def _project_id(task: TaskRow) -> str:
    if task.project_id is None:
        raise AssertionError("Task project_id is required")
    return task.project_id


def test_enqueue_is_idempotent_by_key(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        task = _seed_task(session)
        repository = AsyncTaskRepository(session)

        first = repository.enqueue(
            task_id=task.id,
            request=_request(_project_id(task)),
            idempotency_key="api:test-1",
            now=NOW,
        )
        second = repository.enqueue(
            task_id=task.id,
            request=_request(_project_id(task)),
            idempotency_key="api:test-1",
            now=NOW,
        )
        session.commit()

        count = session.scalar(
            select(AsyncTaskRunRow).count()
        ) if False else len(
            list(session.scalars(select(AsyncTaskRunRow)))
        )

    assert second.id == first.id
    assert count == 1


def test_claim_next_only_claims_one_run(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as seed_session:
        task = _seed_task(seed_session)
        repository = AsyncTaskRepository(seed_session)
        repository.enqueue(
            task_id=task.id,
            request=_request(_project_id(task)),
            idempotency_key="api:claim-1",
            now=NOW,
        )
        seed_session.commit()

    with session_factory() as first_session:
        first = AsyncTaskRepository(first_session).claim_next(
            worker_id="worker-a",
            now=NOW,
            lease_seconds=900,
        )
        first_session.commit()

    with session_factory() as second_session:
        second = AsyncTaskRepository(second_session).claim_next(
            worker_id="worker-b",
            now=NOW,
            lease_seconds=900,
        )
        second_session.commit()

    assert first is not None
    assert first.status is AsyncRunStatus.CLAIMED
    assert first.lease_owner == "worker-a"
    assert first.attempt == 1
    assert second is None


def test_invalid_transition_is_rejected(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        task = _seed_task(session)
        repository = AsyncTaskRepository(session)
        run = repository.enqueue(
            task_id=task.id,
            request=_request(_project_id(task)),
            idempotency_key="api:transition-1",
            now=NOW,
        )

        with pytest.raises(ValueError, match="Invalid async run transition"):
            repository.transition(
                run.id,
                AsyncRunStatus.COMPLETED,
                now=NOW,
            )
