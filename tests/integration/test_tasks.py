from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.audit import AuditWriter
from app.privacy import content_fingerprint
from app.projects import ProjectCreate, ProjectRepository, ProjectService
from app.tasks.models import (
    TaskCreate,
    TaskPriority,
    TaskStatus,
)
from app.tasks.repository import TaskRepository
from app.tasks.service import (
    InvalidTaskTransition,
    TaskCompletionRequiresResult,
    TaskNotFound,
    TaskProjectNotFound,
    TaskService,
)


@pytest.fixture
def session_factory(migrated_engine) -> sessionmaker[Session]:
    return sessionmaker(
        bind=migrated_engine,
        class_=Session,
        expire_on_commit=False,
        autoflush=False,
    )


@pytest.fixture
def task_context(
    session_factory: sessionmaker[Session],
    tmp_path: Path,
) -> tuple[TaskService, str, Path, Session]:
    session = session_factory()
    audit_path = tmp_path / "task-audit.jsonl"
    audit_writer = AuditWriter(audit_path, fsync=False)

    project = ProjectService(
        ProjectRepository(session),
        audit_writer,
    ).create(
        ProjectCreate(
            name="Ánh Dương Core",
            slug="anh-duong-core",
        )
    )

    service = TaskService(
        repository=TaskRepository(session),
        audit_writer=audit_writer,
    )

    try:
        yield service, project.id, audit_path, session
        session.commit()
    finally:
        session.close()


def test_create_and_get_task(
    task_context: tuple[TaskService, str, Path, Session],
) -> None:
    service, project_id, _, _ = task_context

    created = service.create(
        TaskCreate(
            project_id=project_id,
            title="Build Task Registry",
            description="Implement deterministic task lifecycle.",
            priority=TaskPriority.HIGH,
            risk_level=1,
            source_channel="telegram",
            approval_required=False,
        )
    )
    loaded = service.get(created.id)

    assert created.id.startswith("task_")
    assert loaded == created
    assert loaded.project_id == project_id
    assert loaded.status is TaskStatus.RECEIVED
    assert loaded.priority is TaskPriority.HIGH
    assert loaded.version == 1


def test_create_rejects_unknown_project(
    task_context: tuple[TaskService, str, Path, Session],
) -> None:
    service, _, _, _ = task_context

    with pytest.raises(
        TaskProjectNotFound,
        match="proj_missing",
    ):
        service.create(
            TaskCreate(
                project_id="proj_missing",
                title="Orphan task",
                description="Must not be persisted.",
            )
        )


def test_get_missing_task_raises(
    task_context: tuple[TaskService, str, Path, Session],
) -> None:
    service, _, _, _ = task_context

    with pytest.raises(TaskNotFound, match="task_missing"):
        service.get("task_missing")


def test_task_happy_path_requires_result_summary(
    task_context: tuple[TaskService, str, Path, Session],
) -> None:
    service, project_id, _, _ = task_context
    task = service.create(
        TaskCreate(
            project_id=project_id,
            title="Build core",
            description="Complete registry lifecycle.",
        )
    )

    for expected_version, status in (
        (2, TaskStatus.PLANNING),
        (3, TaskStatus.QUEUED),
        (4, TaskStatus.RUNNING),
        (5, TaskStatus.VERIFYING),
    ):
        task = service.transition(task.id, status)
        assert task.version == expected_version

    with pytest.raises(TaskCompletionRequiresResult):
        service.transition(task.id, TaskStatus.COMPLETED)

    completed = service.transition(
        task.id,
        TaskStatus.COMPLETED,
        result_summary="Task Registry implemented and verified.",
    )

    assert completed.status is TaskStatus.COMPLETED
    assert completed.result_summary == (
        "Task Registry implemented and verified."
    )
    assert completed.version == 6


def test_clarifying_and_approval_path_is_valid(
    task_context: tuple[TaskService, str, Path, Session],
) -> None:
    service, project_id, _, _ = task_context
    task = service.create(
        TaskCreate(
            project_id=project_id,
            title="Sensitive task",
            description="Needs approval before queueing.",
            approval_required=True,
            risk_level=2,
        )
    )

    for status in (
        TaskStatus.CLARIFYING,
        TaskStatus.PLANNING,
        TaskStatus.WAITING_APPROVAL,
        TaskStatus.QUEUED,
    ):
        task = service.transition(task.id, status)

    assert task.status is TaskStatus.QUEUED
    assert task.version == 5


def test_invalid_transition_is_rejected_without_mutation(
    task_context: tuple[TaskService, str, Path, Session],
) -> None:
    service, project_id, _, _ = task_context
    task = service.create(
        TaskCreate(
            project_id=project_id,
            title="Invalid transition",
            description="Cannot jump directly to completed.",
        )
    )

    with pytest.raises(
        InvalidTaskTransition,
        match="received -> completed",
    ):
        service.transition(
            task.id,
            TaskStatus.COMPLETED,
            result_summary="Should not be accepted.",
        )

    unchanged = service.get(task.id)
    assert unchanged.status is TaskStatus.RECEIVED
    assert unchanged.version == 1
    assert unchanged.result_summary is None


def test_blocked_task_can_resume_to_planning(
    task_context: tuple[TaskService, str, Path, Session],
) -> None:
    service, project_id, _, _ = task_context
    task = service.create(
        TaskCreate(
            project_id=project_id,
            title="Blocked task",
            description="Resume after blocker is resolved.",
        )
    )
    task = service.transition(task.id, TaskStatus.BLOCKED)
    resumed = service.transition(task.id, TaskStatus.PLANNING)

    assert resumed.status is TaskStatus.PLANNING
    assert resumed.version == 3


def test_failed_task_can_be_requeued(
    task_context: tuple[TaskService, str, Path, Session],
) -> None:
    service, project_id, _, _ = task_context
    task = service.create(
        TaskCreate(
            project_id=project_id,
            title="Retry task",
            description="Retry after a recoverable failure.",
        )
    )
    for status in (
        TaskStatus.PLANNING,
        TaskStatus.QUEUED,
        TaskStatus.RUNNING,
        TaskStatus.FAILED,
        TaskStatus.QUEUED,
    ):
        task = service.transition(
            task.id,
            status,
            result_summary=(
                "First execution failed."
                if status is TaskStatus.FAILED
                else None
            ),
        )

    assert task.status is TaskStatus.QUEUED
    assert task.version == 6


def test_cancel_is_idempotent_for_cancelled_task(
    task_context: tuple[TaskService, str, Path, Session],
) -> None:
    service, project_id, _, _ = task_context
    task = service.create(
        TaskCreate(
            project_id=project_id,
            title="Cancel task",
            description="User cancels before execution.",
        )
    )

    cancelled = service.cancel(
        task.id,
        reason="User changed priority.",
    )
    cancelled_again = service.cancel(task.id)

    assert cancelled.status is TaskStatus.CANCELLED
    assert cancelled.result_summary == "User changed priority."
    assert cancelled_again == cancelled


def test_completed_task_cannot_be_cancelled(
    task_context: tuple[TaskService, str, Path, Session],
) -> None:
    service, project_id, _, _ = task_context
    task = service.create(
        TaskCreate(
            project_id=project_id,
            title="Done task",
            description="Complete before cancellation attempt.",
        )
    )
    for status in (
        TaskStatus.PLANNING,
        TaskStatus.QUEUED,
        TaskStatus.RUNNING,
        TaskStatus.VERIFYING,
    ):
        task = service.transition(task.id, status)

    task = service.transition(
        task.id,
        TaskStatus.COMPLETED,
        result_summary="Completed successfully.",
    )

    with pytest.raises(
        InvalidTaskTransition,
        match="completed -> cancelled",
    ):
        service.cancel(task.id)


def test_list_filters_by_project_and_status(
    task_context: tuple[TaskService, str, Path, Session],
) -> None:
    service, project_id, audit_path, session = task_context

    second_project = ProjectService(
        ProjectRepository(session),
        AuditWriter(
            audit_path,
            fsync=False,
        ),
    ).create(
        ProjectCreate(name="Other Project", slug="other-project")
    )

    first = service.create(
        TaskCreate(
            project_id=project_id,
            title="First",
            description="First project task.",
        )
    )
    second = service.create(
        TaskCreate(
            project_id=project_id,
            title="Second",
            description="Second project task.",
        )
    )
    other = service.create(
        TaskCreate(
            project_id=second_project.id,
            title="Other",
            description="Other project task.",
        )
    )
    second = service.transition(second.id, TaskStatus.PLANNING)

    received = service.list(
        project_id=project_id,
        status=TaskStatus.RECEIVED,
    )

    assert [task.id for task in received] == [first.id]
    assert second.id not in {task.id for task in received}
    assert other.id not in {task.id for task in received}


def test_status_changes_are_written_to_audit(
    task_context: tuple[TaskService, str, Path, Session],
) -> None:
    service, project_id, audit_path, _ = task_context
    task = service.create(
        TaskCreate(
            project_id=project_id,
            title="Audit task",
            description="Verify append-only events.",
        )
    )
    task = service.transition(task.id, TaskStatus.PLANNING)
    task = service.cancel(task.id, reason="No longer needed.")

    records = [
        json.loads(line)
        for line in audit_path.read_text(
            encoding="utf-8"
        ).splitlines()
    ]
    task_records = [
        record
        for record in records
        if record["event_type"].startswith("task.")
    ]

    assert [record["event_type"] for record in task_records] == [
        "task.created",
        "task.status_changed",
        "task.status_changed",
    ]
    assert task_records[-1]["payload"] == {
        "from_status": "planning",
        "project_id": project_id,
        "result_summary_fingerprint": content_fingerprint("No longer needed."),
        "task_id": task.id,
        "to_status": "cancelled",
        "version": 3,
    }


def test_task_audit_does_not_duplicate_raw_result_summary(
    task_context: tuple[TaskService, str, Path, Session],
) -> None:
    service, project_id, audit_path, _ = task_context
    task = service.create(
        TaskCreate(
            project_id=project_id,
            title="Privacy audit test",
            description="Ensure audit stores fingerprints, not result content.",
        )
    )
    for status in (
        TaskStatus.PLANNING,
        TaskStatus.QUEUED,
        TaskStatus.RUNNING,
        TaskStatus.VERIFYING,
    ):
        task = service.transition(task.id, status)

    sensitive_summary = "Nguyễn Văn A phone 0900000000 completed"
    service.transition(
        task.id,
        TaskStatus.COMPLETED,
        result_summary=sensitive_summary,
    )

    records = [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines()]
    event = [record for record in records if record["event_type"] == "task.status_changed"][-1]

    assert sensitive_summary not in audit_path.read_text(encoding="utf-8")
    assert "result_summary" not in event["payload"]
    assert event["payload"]["result_summary_fingerprint"]["chars"] == len(sensitive_summary)
    assert len(event["payload"]["result_summary_fingerprint"]["sha256"]) == 64
