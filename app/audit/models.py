from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


def utc_now() -> datetime:
    return datetime.now(UTC)


def new_audit_id() -> str:
    return f"aud_{uuid4().hex}"


class AuditEvent(BaseModel):
    """Immutable event before redaction and serialization."""

    model_config = ConfigDict(frozen=True)

    event_id: str = Field(
        default_factory=new_audit_id,
        pattern=r"^aud_[0-9a-f]{32}$",
    )
    event_type: str = Field(min_length=1, max_length=128)
    actor: str | None = Field(default=None, max_length=128)
    request_id: str | None = Field(default=None, max_length=128)
    workflow_id: str | None = Field(default=None, max_length=128)
    task_id: str | None = Field(default=None, max_length=128)
    project_id: str | None = Field(default=None, max_length=128)
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)


class AuditIntegrityResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    valid: bool
    line_count: int = Field(ge=0)
    invalid_line_number: int | None = Field(default=None, ge=1)
    error: str | None = None
