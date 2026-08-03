from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import Engine, update
from sqlalchemy.orm import Session, sessionmaker

from app.async_tasks import (
    AsyncTaskCreate,
    AsyncTaskRepository,
)
from app.db.base import Base
from app.db.models import AsyncTaskRunRow, ProjectRow, TaskRow
from app.db.session import create_db_engine
from app.tasks import TaskPriority, TaskStatus

NOW = datetime(2026, 7, 28, 10, 0, tzinfo=UTC)


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    runtime_engine = create_db_engine(
        "sqlite+pysqlite:///"
        f"{tmp_path / 'cancel-race.db'}"
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


def test_cancel_rechecks_database_status_before_mutating(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as seed:
        project = ProjectRow(
            id="proj_cancel_race",
            name="Cancel Race",
            slug="cancel-race",
            status="active",
        )
        task = TaskRow(
            id="task_cancel_race",
            project_id=project.id,
            title="Cancel race",
            description="Cancel race",
            status=TaskStatus.QUEUED.value,
            priority=TaskPriority.NORMAL.value,
            risk_level=0,
            requested_by="test",
            source_channel="api",
            approval_required=False,
        )
        seed.add_all((project, task))
        seed.flush()
        run = AsyncTaskRepository(seed).enqueue(
            task_id=task.id,
            request=AsyncTaskCreate(
                project_id=project.id,
                title="Cancel race",
                goal="Do not overwrite an active run.",
            ),
            idempotency_key="cancel-race",
            now=NOW,
        )
        seed.commit()
        run_id = run.id

    with session_factory() as stale_session:
        repository = AsyncTaskRepository(stale_session)
        cached_row = stale_session.get(
            AsyncTaskRunRow,
            run_id,
        )
        assert cached_row is not None
        assert cached_row.status == "pending"
        stale_session.commit()

        with session_factory() as worker_session:
            worker_session.execute(
                update(AsyncTaskRunRow)
                .where(AsyncTaskRunRow.id == run_id)
                .values(status="running")
            )
            worker_session.commit()

        with pytest.raises(
            ValueError,
            match="running runs cannot be cancelled safely",
        ):
            repository.cancel(run_id, now=NOW)
        stale_session.rollback()

    with session_factory() as verify:
        assert (
            AsyncTaskRepository(verify).get(run_id).status.value
            == "running"
        )
