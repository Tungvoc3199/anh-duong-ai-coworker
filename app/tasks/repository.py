from __future__ import annotations

from uuid import uuid4

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.db.models import ProjectRow, TaskRow
from app.tasks.models import (
    TaskCreate,
    TaskStatus,
)


def new_task_id() -> str:
    return f"task_{uuid4().hex}"


class TaskRepository:
    """SQLAlchemy persistence for Task Registry."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def project_exists(self, project_id: str) -> bool:
        statement = select(ProjectRow.id).where(
            ProjectRow.id == project_id
        )
        return self.session.execute(statement).scalar_one_or_none() is not None

    def create(self, data: TaskCreate) -> TaskRow:
        row = TaskRow(
            id=new_task_id(),
            project_id=data.project_id,
            title=data.title,
            description=data.description,
            status=TaskStatus.RECEIVED.value,
            priority=data.priority.value,
            risk_level=data.risk_level,
            requested_by=data.requested_by,
            source_channel=data.source_channel,
            approval_required=data.approval_required,
            deadline=data.deadline,
        )
        self.session.add(row)
        self.session.flush()
        return row

    def get(self, task_id: str) -> TaskRow | None:
        return self.session.get(TaskRow, task_id)

    def list(
        self,
        *,
        project_id: str | None = None,
        status: TaskStatus | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[TaskRow]:
        statement: Select[tuple[TaskRow]] = select(
            TaskRow
        ).order_by(TaskRow.created_at, TaskRow.id)

        if project_id is not None:
            statement = statement.where(
                TaskRow.project_id == project_id
            )
        if status is not None:
            statement = statement.where(
                TaskRow.status == status.value
            )

        statement = statement.limit(limit).offset(offset)
        return list(self.session.execute(statement).scalars())

    def flush(self) -> None:
        self.session.flush()
