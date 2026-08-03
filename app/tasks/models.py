from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
)


class TaskStatus(StrEnum):
    RECEIVED = "received"
    CLARIFYING = "clarifying"
    PLANNING = "planning"
    WAITING_APPROVAL = "waiting_approval"
    QUEUED = "queued"
    RUNNING = "running"
    VERIFYING = "verifying"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    BLOCKED = "blocked"


class TaskPriority(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


class TaskCreate(BaseModel):
    model_config = ConfigDict(frozen=True)

    project_id: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=255)
    description: str = Field(default="", max_length=20_000)
    priority: TaskPriority = TaskPriority.NORMAL
    risk_level: int = Field(default=0, ge=0, le=4)
    requested_by: str = Field(default="user", min_length=1, max_length=128)
    source_channel: str = Field(default="api", min_length=1, max_length=64)
    approval_required: bool = False
    deadline: datetime | None = None

    @field_validator(
        "project_id",
        "title",
        "requested_by",
        "source_channel",
    )
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("value cannot be blank")
        return normalized

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str) -> str:
        return value.strip()


class Task(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        from_attributes=True,
    )

    id: str
    project_id: str
    title: str
    description: str
    status: TaskStatus
    priority: TaskPriority
    risk_level: int
    requested_by: str
    source_channel: str
    approval_required: bool
    current_step_id: str | None
    result_summary: str | None
    deadline: datetime | None
    created_at: datetime
    updated_at: datetime
    version: int

    @field_validator(
        "deadline",
        "created_at",
        "updated_at",
        mode="before",
    )
    @classmethod
    def normalize_sqlite_datetime(
        cls,
        value: datetime | None,
    ) -> datetime | None:
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value
