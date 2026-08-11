from __future__ import annotations

from uuid import uuid4

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.db.models import ProjectRow
from app.projects.models import ProjectCreate, ProjectStatus


def new_project_id() -> str:
    return f"proj_{uuid4().hex}"


class ProjectRepository:
    """SQLAlchemy persistence for ProjectRow."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, data: ProjectCreate) -> ProjectRow:
        row = ProjectRow(
            id=new_project_id(),
            name=data.name,
            slug=data.slug,
            status=ProjectStatus.IDEA.value,
            priority=data.priority.value,
            path_windows=data.path_windows,
            path_wsl=data.path_wsl,
            repo_url=data.repo_url,
            current_phase=data.current_phase,
            owner=data.owner,
            summary=data.summary,
            next_action=data.next_action,
            constraints=list(data.constraints),
        )
        self.session.add(row)
        self.session.flush()
        return row

    def get(self, project_id: str) -> ProjectRow | None:
        return self.session.get(ProjectRow, project_id)

    def get_by_slug(self, slug: str) -> ProjectRow | None:
        statement = select(ProjectRow).where(
            ProjectRow.slug == slug
        )
        return self.session.execute(statement).scalar_one_or_none()

    def list(
        self,
        *,
        status: ProjectStatus | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ProjectRow]:
        statement: Select[tuple[ProjectRow]] = select(
            ProjectRow
        ).order_by(ProjectRow.created_at, ProjectRow.id)

        if status is not None:
            statement = statement.where(
                ProjectRow.status == status.value
            )

        statement = statement.limit(limit).offset(offset)
        return list(self.session.execute(statement).scalars())

    def flush(self) -> None:
        self.session.flush()
