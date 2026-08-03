from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.audit import AuditWriter
from app.projects.models import (
    ProjectCreate,
    ProjectPriority,
    ProjectStatus,
)
from app.projects.repository import ProjectRepository
from app.projects.service import (
    InvalidProjectTransition,
    ProjectConflict,
    ProjectNotFound,
    ProjectService,
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
def project_service(
    session_factory: sessionmaker[Session],
    tmp_path: Path,
) -> ProjectService:
    session = session_factory()
    service = ProjectService(
        repository=ProjectRepository(session),
        audit_writer=AuditWriter(
            tmp_path / "audit.jsonl",
            fsync=False,
        ),
    )
    try:
        yield service
        session.commit()
    finally:
        session.close()


def test_create_and_get_project(
    project_service: ProjectService,
) -> None:
    created = project_service.create(
        ProjectCreate(
            name="AIOS Dashboard",
            slug="aios-dashboard",
            priority=ProjectPriority.HIGH,
            path_windows=r"F:\AIOS\aios-dashboard",
            path_wsl="/mnt/f/AIOS/aios-dashboard",
            constraints=["local-first"],
        )
    )
    loaded = project_service.get(created.id)

    assert created.id.startswith("proj_")
    assert loaded == created
    assert loaded.status is ProjectStatus.IDEA
    assert loaded.version == 1
    assert loaded.constraints == ("local-first",)


def test_project_slug_is_unique(
    project_service: ProjectService,
) -> None:
    project_service.create(
        ProjectCreate(name="First", slug="same-slug")
    )

    with pytest.raises(ProjectConflict, match="same-slug"):
        project_service.create(
            ProjectCreate(name="Second", slug="same-slug")
        )


def test_slug_is_normalized_before_persistence(
    project_service: ProjectService,
) -> None:
    project = project_service.create(
        ProjectCreate(
            name="Ánh Dương Core",
            slug="  Anh-Duong-Core  ",
        )
    )

    assert project.slug == "anh-duong-core"


def test_get_missing_project_raises(
    project_service: ProjectService,
) -> None:
    with pytest.raises(ProjectNotFound, match="proj_missing"):
        project_service.get("proj_missing")


def test_list_projects_can_filter_by_status(
    project_service: ProjectService,
) -> None:
    idea = project_service.create(
        ProjectCreate(name="Idea", slug="idea")
    )
    active = project_service.create(
        ProjectCreate(name="Active", slug="active")
    )
    project_service.transition(active.id, ProjectStatus.PLANNED)
    active = project_service.transition(
        active.id,
        ProjectStatus.ACTIVE,
    )

    active_projects = project_service.list(
        status=ProjectStatus.ACTIVE
    )

    assert [project.id for project in active_projects] == [active.id]
    assert idea.id not in {project.id for project in active_projects}


def test_happy_path_transitions_increment_version(
    project_service: ProjectService,
) -> None:
    project = project_service.create(
        ProjectCreate(name="Core", slug="core")
    )

    for expected_version, status in (
        (2, ProjectStatus.PLANNED),
        (3, ProjectStatus.ACTIVE),
        (4, ProjectStatus.BLOCKED),
        (5, ProjectStatus.ACTIVE),
        (6, ProjectStatus.COMPLETED),
    ):
        project = project_service.transition(
            project.id,
            status,
        )
        assert project.version == expected_version

    assert project.status is ProjectStatus.COMPLETED


def test_invalid_transition_is_rejected(
    project_service: ProjectService,
) -> None:
    project = project_service.create(
        ProjectCreate(name="Invalid", slug="invalid")
    )

    with pytest.raises(
        InvalidProjectTransition,
        match="idea -> completed",
    ):
        project_service.transition(
            project.id,
            ProjectStatus.COMPLETED,
        )

    unchanged = project_service.get(project.id)
    assert unchanged.status is ProjectStatus.IDEA
    assert unchanged.version == 1


def test_same_state_transition_is_rejected(
    project_service: ProjectService,
) -> None:
    project = project_service.create(
        ProjectCreate(name="Same", slug="same")
    )

    with pytest.raises(
        InvalidProjectTransition,
        match="idea -> idea",
    ):
        project_service.transition(
            project.id,
            ProjectStatus.IDEA,
        )


def test_transition_writes_append_only_audit_event(
    session_factory: sessionmaker[Session],
    tmp_path: Path,
) -> None:
    audit_path = tmp_path / "project-audit.jsonl"
    session = session_factory()
    service = ProjectService(
        repository=ProjectRepository(session),
        audit_writer=AuditWriter(audit_path, fsync=False),
    )
    try:
        project = service.create(
            ProjectCreate(name="Audit", slug="audit")
        )
        session.commit()
        transitioned = service.transition(
            project.id,
            ProjectStatus.PLANNED,
        )
        session.commit()
    finally:
        session.close()

    records = [
        json.loads(line)
        for line in audit_path.read_text(
            encoding="utf-8"
        ).splitlines()
    ]

    assert [record["event_type"] for record in records] == [
        "project.created",
        "project.status_changed",
    ]
    assert records[-1]["payload"] == {
        "from_status": "idea",
        "project_id": project.id,
        "project_slug": "audit",
        "to_status": "planned",
        "version": transitioned.version,
    }


def test_blocked_project_can_pause(
    project_service: ProjectService,
) -> None:
    project = project_service.create(
        ProjectCreate(name="Paused", slug="paused")
    )
    project_service.transition(project.id, ProjectStatus.PLANNED)
    project_service.transition(project.id, ProjectStatus.ACTIVE)
    project_service.transition(project.id, ProjectStatus.BLOCKED)

    paused = project_service.transition(
        project.id,
        ProjectStatus.PAUSED,
    )

    assert paused.status is ProjectStatus.PAUSED


def test_archived_project_is_terminal(
    project_service: ProjectService,
) -> None:
    project = project_service.create(
        ProjectCreate(name="Archive", slug="archive")
    )
    project_service.transition(project.id, ProjectStatus.ARCHIVED)

    with pytest.raises(InvalidProjectTransition):
        project_service.transition(
            project.id,
            ProjectStatus.PLANNED,
        )
