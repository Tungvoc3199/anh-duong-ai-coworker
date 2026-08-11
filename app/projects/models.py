from __future__ import annotations

import re
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
)

_SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class ProjectStatus(StrEnum):
    IDEA = "idea"
    PLANNED = "planned"
    ACTIVE = "active"
    BLOCKED = "blocked"
    PAUSED = "paused"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class ProjectPriority(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


class ProjectCreate(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str = Field(min_length=1, max_length=255)
    slug: str = Field(min_length=1, max_length=255)
    priority: ProjectPriority = ProjectPriority.NORMAL
    path_windows: str | None = None
    path_wsl: str | None = None
    repo_url: str | None = None
    current_phase: str | None = None
    owner: str = Field(default="user", min_length=1, max_length=128)
    summary: str | None = None
    next_action: str | None = None
    constraints: tuple[Any, ...] = ()

    @field_validator("name", "owner")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("value cannot be blank")
        return normalized

    @field_validator("slug")
    @classmethod
    def normalize_slug(cls, value: str) -> str:
        normalized = value.strip().lower().replace("_", "-")
        normalized = re.sub(r"\s+", "-", normalized)
        normalized = re.sub(r"-+", "-", normalized)
        if not _SLUG_PATTERN.fullmatch(normalized):
            raise ValueError(
                "slug must contain lowercase letters, digits and hyphens"
            )
        return normalized


class Project(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        from_attributes=True,
    )

    id: str
    name: str
    slug: str
    status: ProjectStatus
    priority: ProjectPriority
    path_windows: str | None
    path_wsl: str | None
    repo_url: str | None
    current_phase: str | None
    owner: str
    summary: str | None
    next_action: str | None
    constraints: tuple[Any, ...]
    created_at: datetime
    updated_at: datetime
    last_activity_at: datetime | None
    version: int

    @field_validator(
        "created_at",
        "updated_at",
        "last_activity_at",
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
