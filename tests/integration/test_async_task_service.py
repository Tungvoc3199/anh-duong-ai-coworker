from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.async_tasks import (
    AsyncRunStatus,
    AsyncTaskCreate,
    AsyncTaskPolicyGate,
    AsyncTaskRepository,
    AsyncTaskService,
    NotificationStatus,
)
from app.audit import AuditWriter
from app.db.base import Base
from app.db.models import AsyncTaskRunRow, ProjectRow, TaskRow
from app.db.session import create_db_engine
from app.tasks import TaskRepository, TaskService, TaskStatus


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    database_url = (
        "sqlite+pysqlite:///"
        f"{tmp_path / 'async-runner-service.db'}"
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


def _service(
    session: Session,
    tmp_path: Path,
) -> AsyncTaskService:
    audit_writer = AuditWriter(
        tmp_path / "async-service-audit.jsonl",
        fsync=False,
    )
    return AsyncTaskService(
        task_service=TaskService(
            TaskRepository(session),
            audit_writer,
        ),
        repository=AsyncTaskRepository(session),
        policy_gate=AsyncTaskPolicyGate((tmp_path,)),
    )


def _seed_project(session: Session) -> str:
    project = ProjectRow(
        id="proj_async",
        name="Async Project",
        slug="async-project",
        status="active",
    )
    session.add(project)
    session.flush()
    return project.id


def _request(
    project_id: str,
    tmp_path: Path,
    *,
    risk_level: int = 1,
    approval_required: bool = False,
) -> AsyncTaskCreate:
    return AsyncTaskCreate(
        project_id=project_id,
        title="Build async runner",
        goal="Implement the next runner batch",
        risk_level=risk_level,
        approval_required=approval_required,
        workspace=str(tmp_path / "workspace"),
        source_channel="telegram",
        source_chat_id="7535966424",
        idempotency_key="telegram:message-1",
    )


def test_create_queues_allowed_task_and_is_idempotent(
    session_factory: sessionmaker[Session],
    tmp_path: Path,
) -> None:
    with session_factory() as session:
        project_id = _seed_project(session)
        service = _service(session, tmp_path)
        request = _request(project_id, tmp_path)

        first = service.create(request)
        second = service.create(request)
        session.commit()

        task = session.get(TaskRow, first.task_id)
        run = session.get(AsyncTaskRunRow, first.run_id)
        runs = list(session.scalars(select(AsyncTaskRunRow)))

    assert first.replayed is False
    assert second.replayed is True
    assert second.task_id == first.task_id
    assert second.run_id == first.run_id
    assert second.status is first.status
    assert task is not None
    assert task.status == TaskStatus.QUEUED.value
    assert run is not None
    assert run.status == AsyncRunStatus.PENDING.value
    assert len(runs) == 1


def test_create_queues_risk_two_for_step_level_execution(
    session_factory: sessionmaker[Session],
    tmp_path: Path,
) -> None:
    with session_factory() as session:
        project_id = _seed_project(session)
        service = _service(session, tmp_path)

        accepted = service.create(
            _request(
                project_id,
                tmp_path,
                risk_level=2,
            )
        )
        session.commit()

        task = session.get(TaskRow, accepted.task_id)
        run = session.get(AsyncTaskRunRow, accepted.run_id)

    assert task is not None
    assert task.status == TaskStatus.QUEUED.value
    assert run is not None
    assert run.status == AsyncRunStatus.PENDING.value


def test_create_queues_approval_required_task_without_raw_block(
    session_factory: sessionmaker[Session],
    tmp_path: Path,
) -> None:
    with session_factory() as session:
        project_id = _seed_project(session)
        service = _service(session, tmp_path)

        accepted = service.create(
            _request(
                project_id,
                tmp_path,
                risk_level=2,
                approval_required=True,
            )
        )
        session.commit()

        task = session.get(TaskRow, accepted.task_id)
        run = session.get(AsyncTaskRunRow, accepted.run_id)

    assert accepted.status is AsyncRunStatus.PENDING
    assert task is not None
    assert task.status == TaskStatus.QUEUED.value
    assert run is not None
    assert run.status == AsyncRunStatus.PENDING.value
    assert run.source_chat_id == "7535966424"
    assert run.notification_status == NotificationStatus.NOT_REQUIRED.value
    assert run.last_error_code is None
    assert run.last_error_message is None
