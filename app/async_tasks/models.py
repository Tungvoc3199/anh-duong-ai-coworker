from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from app.tasks.models import TaskPriority


class AsyncRunStatus(StrEnum):
    PENDING = "pending"
    CLAIMED = "claimed"
    RUNNING = "running"
    RETRY_WAIT = "retry_wait"
    VERIFYING = "verifying"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"


class AsyncTaskMode(StrEnum):
    QUICK = "quick"
    BUILD = "build"


class NotificationStatus(StrEnum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"
    NOT_REQUIRED = "not_required"


ASYNC_RUN_TRANSITIONS: dict[
    AsyncRunStatus,
    frozenset[AsyncRunStatus],
] = {
    AsyncRunStatus.PENDING: frozenset(
        {
            AsyncRunStatus.CLAIMED,
            AsyncRunStatus.CANCELLED,
        }
    ),
    AsyncRunStatus.CLAIMED: frozenset(
        {
            AsyncRunStatus.RUNNING,
            AsyncRunStatus.PENDING,
            AsyncRunStatus.BLOCKED,
        }
    ),
    AsyncRunStatus.RUNNING: frozenset(
        {
            AsyncRunStatus.VERIFYING,
            AsyncRunStatus.RETRY_WAIT,
            AsyncRunStatus.FAILED,
            AsyncRunStatus.BLOCKED,
        }
    ),
    AsyncRunStatus.RETRY_WAIT: frozenset(
        {
            AsyncRunStatus.CLAIMED,
            AsyncRunStatus.CANCELLED,
        }
    ),
    AsyncRunStatus.VERIFYING: frozenset(
        {
            AsyncRunStatus.COMPLETED,
            AsyncRunStatus.FAILED,
            AsyncRunStatus.BLOCKED,
        }
    ),
    AsyncRunStatus.COMPLETED: frozenset(),
    AsyncRunStatus.FAILED: frozenset(),
    AsyncRunStatus.BLOCKED: frozenset(
        {
            AsyncRunStatus.PENDING,
        }
    ),
    AsyncRunStatus.CANCELLED: frozenset(),
}


class AsyncTaskCreate(BaseModel):
    model_config = ConfigDict(frozen=True)

    project_id: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=255)
    goal: str = Field(min_length=1, max_length=20_000)
    mode: AsyncTaskMode = AsyncTaskMode.BUILD
    priority: TaskPriority = TaskPriority.NORMAL
    risk_level: int = Field(default=0, ge=0, le=4)
    approval_required: bool = False
    workspace: str | None = Field(default=None, max_length=1024)
    requested_by: str = Field(
        default="user",
        min_length=1,
        max_length=128,
    )
    source_channel: str = Field(
        default="api",
        min_length=1,
        max_length=64,
    )
    source_chat_id: str | None = Field(
        default=None,
        max_length=128,
    )
    source_session_id: str | None = Field(default=None, max_length=128)
    source_message_id: str | None = Field(default=None, max_length=128)
    correlation_id: str | None = Field(default=None, max_length=128)
    idempotency_key: str | None = Field(
        default=None,
        max_length=255,
    )
    deadline: datetime | None = None
    constraints: tuple[str, ...] = ()
    governed_coding: dict[str, Any] | None = None

    @field_validator(
        "project_id",
        "title",
        "goal",
        "requested_by",
        "source_channel",
    )
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("value cannot be blank")
        return normalized

    @field_validator("deadline", mode="before")
    @classmethod
    def normalize_deadline(cls, value: Any) -> Any:
        if isinstance(value, datetime) and value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value

    @model_validator(mode="after")
    def require_telegram_idempotency(self) -> AsyncTaskCreate:
        if (
            self.source_channel == "telegram"
            and not self.idempotency_key
        ):
            raise ValueError(
                "Telegram tasks require idempotency_key"
            )
        return self


class ApprovalResolveRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    action: str = Field(min_length=1, max_length=255)
    resolved_by: str = Field(min_length=1, max_length=128)
    approved: bool = True

class AsyncTaskAccepted(BaseModel):
    model_config = ConfigDict(frozen=True)

    task_id: str
    run_id: str
    status: AsyncRunStatus
    message: str = "ACCEPTED"
    replayed: bool = False


class AsyncExecutionCheckpoint(BaseModel):
    model_config = ConfigDict(frozen=True)

    stage: str
    message: str
    external_run_id: str | None = None
    uncertain_side_effect: bool = False
    updated_at: datetime


class AsyncExecutionResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    outcome: str
    summary: str
    artifacts: tuple[str, ...] = ()
    verification: tuple[str, ...] = ()
    external_run_id: str | None = None


class AsyncRunError(BaseModel):
    model_config = ConfigDict(frozen=True)

    code: str
    message: str
    retryable: bool
    uncertain_side_effect: bool = False


class AsyncTaskRun(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        from_attributes=True,
    )

    id: str
    task_id: str
    status: AsyncRunStatus
    mode: AsyncTaskMode
    goal: str
    workspace: str | None
    request_json: str
    checkpoint_json: str | None
    result_json: str | None
    attempt: int
    max_attempts: int
    run_after: datetime
    lease_owner: str | None
    lease_expires_at: datetime | None
    idempotency_key: str
    external_run_id: str | None
    last_error_code: str | None
    last_error_message: str | None
    source_chat_id: str | None
    notification_status: NotificationStatus
    notification_attempts: int
    created_at: datetime
    updated_at: datetime
    version: int

    @field_validator(
        "run_after",
        "lease_expires_at",
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
