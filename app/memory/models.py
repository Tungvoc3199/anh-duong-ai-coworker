from __future__ import annotations

import json
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
)


class MemoryType(StrEnum):
    WORKING = "working"
    SESSION = "session"
    PROJECT = "project"
    USER = "user"
    EPISODIC = "episodic"
    SEMANTIC = "semantic"


class Memory(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        from_attributes=True,
    )

    id: str
    memory_type: MemoryType
    scope_id: str
    title: str
    content: str
    summary: str | None
    importance: float
    confidence: float
    source: str | None
    expires_at: datetime | None
    tags: tuple[str, ...]
    created_at: datetime
    updated_at: datetime
    version: int

    @field_validator(
        "expires_at",
        "created_at",
        "updated_at",
        mode="before",
    )
    @classmethod
    def normalize_sqlite_datetime(cls, value: Any) -> Any:
        if isinstance(value, datetime) and value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value

    @field_validator("tags", mode="before")
    @classmethod
    def normalize_sqlite_tags(cls, value: Any) -> Any:
        if isinstance(value, str):
            parsed = json.loads(value)
            if not isinstance(parsed, list):
                raise ValueError("tags JSON must contain a list")
            return tuple(str(item) for item in parsed)
        return value


class MemoryUpdate(BaseModel):
    model_config = ConfigDict(frozen=True)

    title: str | None = Field(default=None, min_length=1, max_length=255)
    content: str | None = Field(default=None, min_length=1)
    summary: str | None = None
    importance: float | None = Field(default=None, ge=0.0, le=1.0)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    source: str | None = Field(default=None, max_length=255)
    expires_at: datetime | None = None
    tags: tuple[str, ...] | None = None

    @field_validator("title", "content")
    @classmethod
    def strip_required_text(
        cls,
        value: str | None,
    ) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("value cannot be blank")
        return normalized


class MemorySearchResult(Memory):
    fts_rank: float
