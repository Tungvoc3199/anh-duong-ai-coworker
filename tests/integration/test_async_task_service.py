from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime
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
from app.db.models import ApprovalRow, AsyncTaskRunRow, ProjectRow, TaskRow, WorkflowRow
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
        repository=AsyncTaskRepository(session, audit_writer=audit_writer),
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


def test_create_persists_durable_goal_plan(
    session_factory: sessionmaker[Session],
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    with session_factory() as session:
        project_id = _seed_project(session)
        service = _service(session, tmp_path)

        accepted = service.create(_request(project_id, tmp_path))
        session.commit()

        workflow = session.get(WorkflowRow, accepted.run_id)

    assert workflow is not None
    assert workflow.task_id == accepted.task_id
    assert workflow.plan_payload["status"] == "ready"
    assert workflow.plan_payload["goal"]["statement"] == "Implement the next runner batch"
    assert workflow.plan_payload["truth"]["project_id"] == project_id
    assert workflow.plan_payload["nodes"][-1]["kind"] == "verification_gate"
    assert "source_channel" not in workflow.plan_payload


def test_ambiguous_goal_blocks_before_worker_queue(
    session_factory: sessionmaker[Session],
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    with session_factory() as session:
        project_id = _seed_project(session)
        service = _service(session, tmp_path)
        request = _request(project_id, tmp_path).model_copy(
            update={
                "goal": "do it",
                "idempotency_key": "telegram:ambiguous",
            }
        )

        accepted = service.create(request)
        session.commit()

        task = session.get(TaskRow, accepted.task_id)
        run = session.get(AsyncTaskRunRow, accepted.run_id)
        workflow = session.get(WorkflowRow, accepted.run_id)

    assert accepted.status is AsyncRunStatus.BLOCKED
    assert task is not None
    assert task.status == TaskStatus.BLOCKED.value
    assert run is not None
    assert run.status == AsyncRunStatus.BLOCKED.value
    assert run.last_error_code == "planning_blocked"
    assert workflow is not None
    assert workflow.plan_payload["status"] == "blocked"
    blocker = workflow.plan_payload["blocker"]
    assert blocker["question"]
    assert blocker["reason"]

def test_planning_blocker_does_not_create_approval(
    session_factory: sessionmaker[Session],
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    with session_factory() as session:
        project_id = _seed_project(session)
        service = _service(session, tmp_path)
        request = _request(
            project_id, tmp_path, risk_level=2, approval_required=True
        ).model_copy(
            update={
                "goal": "do it",
                "idempotency_key": "telegram:ambiguous-approval",
            }
        )

        accepted = service.create(request)
        session.commit()
        approvals = list(session.scalars(select(ApprovalRow)))

    assert accepted.status is AsyncRunStatus.BLOCKED
    assert approvals == []


def test_long_idempotency_key_still_creates_bounded_plan_id(
    session_factory: sessionmaker[Session],
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    with session_factory() as session:
        project_id = _seed_project(session)
        service = _service(session, tmp_path)
        long_key = "telegram:" + ("x" * 240)
        request = _request(project_id, tmp_path).model_copy(
            update={"idempotency_key": long_key}
        )

        accepted = service.create(request)
        session.commit()
        workflow = session.get(WorkflowRow, accepted.run_id)

    assert accepted.status is AsyncRunStatus.PENDING
    assert workflow is not None
    assert len(workflow.plan_payload["id"]) <= 128

def test_policy_denied_request_does_not_persist_plan(
    session_factory: sessionmaker[Session],
    tmp_path: Path,
) -> None:
    with session_factory() as session:
        project_id = _seed_project(session)
        service = _service(session, tmp_path)
        request = _request(project_id, tmp_path).model_copy(
            update={
                "workspace": "/etc",
                "idempotency_key": "telegram:workspace-denied",
            }
        )

        accepted = service.create(request)
        session.commit()
        workflow = session.get(WorkflowRow, accepted.run_id)

    assert accepted.status is AsyncRunStatus.BLOCKED
    assert workflow is None


def test_planning_blocked_audit_reason_is_not_policy_gate(
    session_factory: sessionmaker[Session],
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    with session_factory() as session:
        project_id = _seed_project(session)
        service = _service(session, tmp_path)
        request = _request(project_id, tmp_path).model_copy(
            update={
                "goal": "do it",
                "idempotency_key": "telegram:audit-planning-blocked",
            }
        )
        service.create(request)
        session.commit()

    records = [
        json.loads(line)
        for line in (tmp_path / "async-service-audit.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    blocked = [
        record
        for record in records
        if record["event_type"] == "async_run.blocked"
    ]
    assert blocked
    assert blocked[-1]["payload"]["reason"] == "planning_blocked"

def test_whitespace_equivalent_idempotency_key_replays_same_task_and_run(
    session_factory: sessionmaker[Session],
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    with session_factory() as session:
        project_id = _seed_project(session)
        service = _service(session, tmp_path)
        first_request = _request(project_id, tmp_path).model_copy(
            update={"idempotency_key": "telegram:normalized-key"}
        )
        replay_request = first_request.model_copy(
            update={"idempotency_key": "  telegram:normalized-key  "}
        )

        first = service.create(first_request)
        replay = service.create(replay_request)
        session.commit()
        tasks = list(session.scalars(select(TaskRow)))
        runs = list(session.scalars(select(AsyncTaskRunRow)))

    assert replay.replayed is True
    assert replay.task_id == first.task_id
    assert replay.run_id == first.run_id
    assert len(tasks) == 1
    assert len(runs) == 1


def test_pseudonymous_telegram_key_replays_legacy_raw_idempotency_row(
    session_factory: sessionmaker[Session],
    tmp_path: Path,
) -> None:
    from app.privacy import telegram_idempotency_key
    from app.tasks import TaskCreate

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    with session_factory() as session:
        project_id = _seed_project(session)
        service = _service(session, tmp_path)
        legacy = _request(project_id, tmp_path).model_copy(
            update={
                "source_message_id": "message-1",
                "idempotency_key": "telegram:7535966424:message-1",
            }
        )
        legacy_task = service.task_service.create(
            TaskCreate(
                project_id=project_id,
                title="Legacy Telegram task",
                description=legacy.goal,
                source_channel="telegram",
            )
        )
        first = service.repository.enqueue(
            task_id=legacy_task.id,
            request=legacy,
            idempotency_key=legacy.idempotency_key or "",
        )
        legacy_row = session.get(AsyncTaskRunRow, first.id)
        assert legacy_row is not None
        legacy_row.idempotency_key = legacy.idempotency_key or ""
        session.flush()
        replay = service.create(
            legacy.model_copy(
                update={
                    "idempotency_key": telegram_idempotency_key(
                        source_chat_id="7535966424",
                        source_message_id="message-1",
                    )
                }
            )
        )
        session.commit()
        runs = list(session.scalars(select(AsyncTaskRunRow)))
    assert replay.replayed is True
    assert replay.task_id == first.task_id
    assert replay.run_id == first.id
    assert len(runs) == 1



def test_pseudonymous_telegram_key_replays_legacy_custom_idempotency_row(
    session_factory: sessionmaker[Session],
    tmp_path: Path,
) -> None:
    from app.tasks import TaskCreate

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    with session_factory() as session:
        project_id = _seed_project(session)
        service = _service(session, tmp_path)
        legacy = _request(project_id, tmp_path).model_copy(
            update={
                "source_message_id": "message-custom",
                "idempotency_key": "telegram:message-custom",
            }
        )
        legacy_task = service.task_service.create(
            TaskCreate(
                project_id=project_id,
                title="Legacy custom Telegram task",
                description=legacy.goal,
                source_channel="telegram",
            )
        )
        first = service.repository.enqueue(
            task_id=legacy_task.id,
            request=legacy,
            idempotency_key=legacy.idempotency_key or "",
        )
        legacy_row = session.get(AsyncTaskRunRow, first.id)
        assert legacy_row is not None
        legacy_row.idempotency_key = legacy.idempotency_key or ""
        session.flush()
        replay = service.create(legacy)
        session.commit()
        runs = list(session.scalars(select(AsyncTaskRunRow)))

    assert replay.replayed is True
    assert replay.task_id == first.task_id
    assert replay.run_id == first.id
    assert len(runs) == 1

def test_new_telegram_run_persists_only_canonical_pseudonymous_idempotency_key(
    session_factory: sessionmaker[Session],
    tmp_path: Path,
) -> None:
    from app.privacy import telegram_idempotency_key

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    raw_key = "telegram:7535966424:message-2"
    with session_factory() as session:
        project_id = _seed_project(session)
        service = _service(session, tmp_path)
        request = _request(project_id, tmp_path).model_copy(
            update={
                "source_message_id": "message-2",
                "idempotency_key": raw_key,
            }
        )
        accepted = service.create(request)
        session.commit()
        run = session.get(AsyncTaskRunRow, accepted.run_id)
    assert run is not None
    expected = telegram_idempotency_key(
        source_chat_id="7535966424",
        source_message_id="message-2",
    )
    payload = json.loads(run.request_json)
    assert run.idempotency_key == expected
    assert payload["idempotency_key"] == expected
    assert raw_key not in run.request_json
    assert "7535966424" not in run.request_json
    assert "message-2" not in run.request_json


def test_scoped_approval_continuation_resumes_same_telegram_run(
    session_factory: sessionmaker[Session],
    tmp_path: Path,
) -> None:
    with session_factory() as session:
        project_id = _seed_project(session)
        service = _service(session, tmp_path)
        request = _request(project_id, tmp_path, risk_level=2, approval_required=True).model_copy(
            update={
                "goal": "Publish the image to Facebook",
                "source_session_id": "telegram-session-1",
                "source_message_id": "approval-message-1",
                "idempotency_key": "telegram:approval-message-1",
            }
        )
        accepted = service.create(request)
        claimed = service.repository.claim_next(
            worker_id="approval-worker", now=datetime.now(UTC), lease_seconds=60
        )
        assert claimed is not None
        service.repository.transition(claimed.id, AsyncRunStatus.BLOCKED, now=datetime.now(UTC))
        resumed_run = service.resolve_latest_approval(
            source_chat_id="7535966424",
            source_session_id="telegram-session-1",
            resolved_by="telegram:owner",
            approved=True,
        )
        approval = session.scalars(select(ApprovalRow)).one()
        session.commit()

    assert resumed_run.id == accepted.run_id
    assert resumed_run.status is AsyncRunStatus.PENDING
    assert approval.status == "approved"
