from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError

from app.audit import AuditEvent, AuditWriter
from app.db.models import ProjectRow
from app.projects.models import (
    Project,
    ProjectCreate,
    ProjectStatus,
)
from app.projects.repository import ProjectRepository

PROJECT_TRANSITIONS: dict[
    ProjectStatus,
    frozenset[ProjectStatus],
] = {
    ProjectStatus.IDEA: frozenset(
        {
            ProjectStatus.PLANNED,
            ProjectStatus.ARCHIVED,
        }
    ),
    ProjectStatus.PLANNED: frozenset(
        {
            ProjectStatus.ACTIVE,
            ProjectStatus.PAUSED,
            ProjectStatus.ARCHIVED,
        }
    ),
    ProjectStatus.ACTIVE: frozenset(
        {
            ProjectStatus.BLOCKED,
            ProjectStatus.PAUSED,
            ProjectStatus.COMPLETED,
            ProjectStatus.ARCHIVED,
        }
    ),
    ProjectStatus.BLOCKED: frozenset(
        {
            ProjectStatus.ACTIVE,
            ProjectStatus.PAUSED,
            ProjectStatus.ARCHIVED,
        }
    ),
    ProjectStatus.PAUSED: frozenset(
        {
            ProjectStatus.ACTIVE,
            ProjectStatus.ARCHIVED,
        }
    ),
    ProjectStatus.COMPLETED: frozenset(
        {
            ProjectStatus.ARCHIVED,
        }
    ),
    ProjectStatus.ARCHIVED: frozenset(),
}


class ProjectServiceError(RuntimeError):
    """Base error for Project Registry operations."""


class ProjectConflict(ProjectServiceError):
    """Raised when a unique project field already exists."""


class ProjectNotFound(ProjectServiceError):
    """Raised when the requested project is absent."""


class InvalidProjectTransition(ProjectServiceError):
    """Raised when a transition violates the state machine."""


class ProjectService:
    def __init__(
        self,
        repository: ProjectRepository,
        audit_writer: AuditWriter,
    ) -> None:
        self.repository = repository
        self.audit_writer = audit_writer

    def create(self, data: ProjectCreate) -> Project:
        if self.repository.get_by_slug(data.slug) is not None:
            raise ProjectConflict(
                f"Project slug already exists: {data.slug}"
            )

        try:
            row = self.repository.create(data)
        except IntegrityError as exc:
            self.repository.session.rollback()
            raise ProjectConflict(
                f"Project slug already exists: {data.slug}"
            ) from exc

        project = self._to_project(row)
        self.audit_writer.write(
            AuditEvent(
                event_type="project.created",
                actor="user",
                project_id=project.id,
                payload={
                    "project_id": project.id,
                    "project_slug": project.slug,
                    "status": project.status.value,
                    "version": project.version,
                },
            )
        )
        return project

    def get(self, project_id: str) -> Project:
        return self._to_project(self._require_row(project_id))

    def list(
        self,
        *,
        status: ProjectStatus | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Project]:
        if not 1 <= limit <= 500:
            raise ValueError("limit must be between 1 and 500")
        if offset < 0:
            raise ValueError("offset cannot be negative")

        return [
            self._to_project(row)
            for row in self.repository.list(
                status=status,
                limit=limit,
                offset=offset,
            )
        ]

    def transition(
        self,
        project_id: str,
        target_status: ProjectStatus,
    ) -> Project:
        row = self._require_row(project_id)
        current_status = ProjectStatus(row.status)

        if target_status not in PROJECT_TRANSITIONS[current_status]:
            raise InvalidProjectTransition(
                "Invalid project transition: "
                f"{current_status.value} -> {target_status.value}"
            )

        row.status = target_status.value
        row.version += 1
        now = datetime.now(UTC)
        row.updated_at = now
        row.last_activity_at = now
        self.repository.flush()

        project = self._to_project(row)
        self.audit_writer.write(
            AuditEvent(
                event_type="project.status_changed",
                actor="user",
                project_id=project.id,
                payload={
                    "from_status": current_status.value,
                    "project_id": project.id,
                    "project_slug": project.slug,
                    "to_status": project.status.value,
                    "version": project.version,
                },
            )
        )
        return project

    def _require_row(self, project_id: str) -> ProjectRow:
        row = self.repository.get(project_id)
        if row is None:
            raise ProjectNotFound(
                f"Project not found: {project_id}"
            )
        return row

    @staticmethod
    def _to_project(row: ProjectRow) -> Project:
        return Project.model_validate(row)
