from __future__ import annotations

from datetime import UTC, datetime

from app.audit import AuditEvent, AuditWriter
from app.db.models import TaskRow
from app.tasks.models import (
    Task,
    TaskCreate,
    TaskStatus,
)
from app.tasks.repository import TaskRepository

TASK_TRANSITIONS: dict[
    TaskStatus,
    frozenset[TaskStatus],
] = {
    TaskStatus.RECEIVED: frozenset(
        {
            TaskStatus.CLARIFYING,
            TaskStatus.PLANNING,
            TaskStatus.BLOCKED,
            TaskStatus.CANCELLED,
        }
    ),
    TaskStatus.CLARIFYING: frozenset(
        {
            TaskStatus.PLANNING,
            TaskStatus.BLOCKED,
            TaskStatus.CANCELLED,
        }
    ),
    TaskStatus.PLANNING: frozenset(
        {
            TaskStatus.WAITING_APPROVAL,
            TaskStatus.QUEUED,
            TaskStatus.BLOCKED,
            TaskStatus.CANCELLED,
        }
    ),
    TaskStatus.WAITING_APPROVAL: frozenset(
        {
            TaskStatus.PLANNING,
            TaskStatus.QUEUED,
            TaskStatus.BLOCKED,
            TaskStatus.CANCELLED,
        }
    ),
    TaskStatus.QUEUED: frozenset(
        {
            TaskStatus.RUNNING,
            TaskStatus.BLOCKED,
            TaskStatus.CANCELLED,
        }
    ),
    TaskStatus.RUNNING: frozenset(
        {
            TaskStatus.VERIFYING,
            TaskStatus.FAILED,
            TaskStatus.BLOCKED,
            TaskStatus.CANCELLED,
        }
    ),
    TaskStatus.VERIFYING: frozenset(
        {
            TaskStatus.RUNNING,
            TaskStatus.COMPLETED,
            TaskStatus.FAILED,
            TaskStatus.BLOCKED,
            TaskStatus.CANCELLED,
        }
    ),
    TaskStatus.BLOCKED: frozenset(
        {
            TaskStatus.CLARIFYING,
            TaskStatus.PLANNING,
            TaskStatus.QUEUED,
            TaskStatus.RUNNING,
            TaskStatus.CANCELLED,
        }
    ),
    TaskStatus.FAILED: frozenset(
        {
            TaskStatus.PLANNING,
            TaskStatus.QUEUED,
            TaskStatus.CANCELLED,
        }
    ),
    TaskStatus.COMPLETED: frozenset(),
    TaskStatus.CANCELLED: frozenset(),
}


class TaskServiceError(RuntimeError):
    """Base error for Task Registry operations."""


class TaskNotFound(TaskServiceError):
    """Raised when a task ID does not exist."""


class TaskProjectNotFound(TaskServiceError):
    """Raised when a task references an unknown project."""


class InvalidTaskTransition(TaskServiceError):
    """Raised when a status transition violates the state machine."""


class TaskCompletionRequiresResult(TaskServiceError):
    """Raised when completed status has no result summary."""


class TaskService:
    def __init__(
        self,
        repository: TaskRepository,
        audit_writer: AuditWriter,
    ) -> None:
        self.repository = repository
        self.audit_writer = audit_writer

    def create(self, data: TaskCreate) -> Task:
        if not self.repository.project_exists(data.project_id):
            raise TaskProjectNotFound(
                f"Task project not found: {data.project_id}"
            )

        row = self.repository.create(data)
        task = self._to_task(row)

        self.audit_writer.write(
            AuditEvent(
                event_type="task.created",
                actor=data.requested_by,
                task_id=task.id,
                project_id=task.project_id,
                payload={
                    "approval_required": task.approval_required,
                    "priority": task.priority.value,
                    "project_id": task.project_id,
                    "risk_level": task.risk_level,
                    "status": task.status.value,
                    "task_id": task.id,
                    "version": task.version,
                },
            )
        )
        return task

    def get(self, task_id: str) -> Task:
        return self._to_task(self._require_row(task_id))

    def list(
        self,
        *,
        project_id: str | None = None,
        status: TaskStatus | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Task]:
        if not 1 <= limit <= 500:
            raise ValueError("limit must be between 1 and 500")
        if offset < 0:
            raise ValueError("offset cannot be negative")

        return [
            self._to_task(row)
            for row in self.repository.list(
                project_id=project_id,
                status=status,
                limit=limit,
                offset=offset,
            )
        ]

    def transition(
        self,
        task_id: str,
        target_status: TaskStatus,
        *,
        result_summary: str | None = None,
        current_step_id: str | None = None,
    ) -> Task:
        row = self._require_row(task_id)
        current_status = TaskStatus(row.status)

        if target_status not in TASK_TRANSITIONS[current_status]:
            raise InvalidTaskTransition(
                "Invalid task transition: "
                f"{current_status.value} -> {target_status.value}"
            )

        normalized_result = self._normalize_optional_text(
            result_summary
        )
        if (
            target_status is TaskStatus.COMPLETED
            and normalized_result is None
        ):
            raise TaskCompletionRequiresResult(
                "Completed task requires result_summary"
            )

        row.status = target_status.value
        row.version += 1
        row.updated_at = datetime.now(UTC)

        if normalized_result is not None:
            row.result_summary = normalized_result
        if current_step_id is not None:
            row.current_step_id = current_step_id.strip() or None

        self.repository.flush()
        task = self._to_task(row)

        self.audit_writer.write(
            AuditEvent(
                event_type="task.status_changed",
                actor="system",
                task_id=task.id,
                project_id=task.project_id,
                payload={
                    "from_status": current_status.value,
                    "project_id": task.project_id,
                    "result_summary": task.result_summary,
                    "task_id": task.id,
                    "to_status": task.status.value,
                    "version": task.version,
                },
            )
        )
        return task

    def cancel(
        self,
        task_id: str,
        *,
        reason: str | None = None,
    ) -> Task:
        task = self.get(task_id)
        if task.status is TaskStatus.CANCELLED:
            return task

        return self.transition(
            task_id,
            TaskStatus.CANCELLED,
            result_summary=reason,
        )

    def _require_row(self, task_id: str) -> TaskRow:
        row = self.repository.get(task_id)
        if row is None:
            raise TaskNotFound(f"Task not found: {task_id}")
        return row

    @staticmethod
    def _normalize_optional_text(value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @staticmethod
    def _to_task(row: TaskRow) -> Task:
        return Task.model_validate(row)
