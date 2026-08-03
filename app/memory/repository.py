from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, cast
from uuid import uuid4

from sqlalchemy import delete, select, text
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from app.audit import SecretRedactor
from app.db.models import MemoryRow
from app.memory.models import (
    Memory,
    MemorySearchResult,
    MemoryType,
    MemoryUpdate,
)

_FTS_TOKEN_PATTERN = re.compile(r"[^\W_]+", flags=re.UNICODE)
_StringList = list[str]
_SENSITIVE_TAG_KEY_PATTERN = re.compile(
    r"""
    ^
    (
        api[_-]?key
        |access[_-]?token
        |auth[_-]?token
        |authorization
        |bot[_-]?token
        |client[_-]?secret
        |gateway[_-]?token
        |openclaw[_-]?gateway[_-]?token
        |password
        |passwd
        |private[_-]?key
        |refresh[_-]?token
        |secret
        |session[_-]?token
    )
    $
    """,
    flags=re.IGNORECASE | re.VERBOSE,
)


def new_memory_id() -> str:
    return f"mem_{uuid4().hex}"


class MemoryRepositoryError(RuntimeError):
    """Base error for Memory Repository operations."""


class MemoryNotFound(MemoryRepositoryError):
    """Raised when a requested memory does not exist."""


class MemoryRepository:
    """SQLite memory persistence with an FTS5 external-content index."""

    def __init__(
        self,
        session: Session,
        *,
        redactor: SecretRedactor | None = None,
    ) -> None:
        self.session = session
        self.redactor = redactor or SecretRedactor()

    def create(
        self,
        *,
        memory_type: MemoryType | str,
        scope_id: str,
        title: str,
        content: str,
        summary: str | None = None,
        importance: float = 0.5,
        confidence: float = 1.0,
        source: str | None = None,
        expires_at: datetime | None = None,
        tags: tuple[str, ...] | list[str] = (),
    ) -> Memory:
        normalized_scope = self._required_text(scope_id, "scope_id")
        normalized_title = self._required_text(title, "title")
        normalized_content = self._required_text(content, "content")
        normalized_type = MemoryType(memory_type)

        if not 0.0 <= importance <= 1.0:
            raise ValueError("importance must be between 0 and 1")
        if not 0.0 <= confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")

        row = MemoryRow(
            id=new_memory_id(),
            memory_type=normalized_type.value,
            scope_id=normalized_scope,
            title=self._redact_text(normalized_title),
            content=self._redact_text(normalized_content),
            summary=self._redact_optional_text(summary),
            importance=importance,
            confidence=confidence,
            source=self._redact_optional_text(source),
            expires_at=expires_at,
            tags=self._redact_tags(tags),
        )
        self.session.add(row)
        self.session.flush()
        return self._to_memory(row)

    def get(self, memory_id: str) -> Memory:
        return self._to_memory(self._require_row(memory_id))

    def update(
        self,
        memory_id: str,
        changes: MemoryUpdate,
    ) -> Memory:
        row = self._require_row(memory_id)
        fields = changes.model_fields_set

        if "title" in fields:
            row.title = self._redact_text(
                self._required_text(changes.title, "title")
            )
        if "content" in fields:
            row.content = self._redact_text(
                self._required_text(changes.content, "content")
            )
        if "summary" in fields:
            row.summary = self._redact_optional_text(changes.summary)
        if "importance" in fields:
            row.importance = self._required_number(
                changes.importance,
                "importance",
            )
        if "confidence" in fields:
            row.confidence = self._required_number(
                changes.confidence,
                "confidence",
            )
        if "source" in fields:
            row.source = self._redact_optional_text(changes.source)
        if "expires_at" in fields:
            row.expires_at = changes.expires_at
        if "tags" in fields:
            row.tags = self._redact_tags(changes.tags or ())

        row.version += 1
        row.updated_at = datetime.now(UTC)
        self.session.flush()
        return self._to_memory(row)

    def delete(self, memory_id: str) -> bool:
        result = cast(
            CursorResult[Any],
            self.session.execute(
                delete(MemoryRow).where(
                    MemoryRow.id == memory_id
                )
            ),
        )
        self.session.flush()
        return bool(result.rowcount)

    def search_fts(
        self,
        query: str,
        *,
        scope_id: str | None = None,
        memory_type: MemoryType | str | None = None,
        limit: int = 20,
        include_expired: bool = False,
    ) -> list[MemorySearchResult]:
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")

        fts_query = self._build_fts_query(query)
        if fts_query is None:
            return []

        filters = ["memories_fts MATCH :fts_query"]
        parameters: dict[str, Any] = {
            "fts_query": fts_query,
            "limit": limit,
        }

        if scope_id is not None:
            filters.append("m.scope_id = :scope_id")
            parameters["scope_id"] = scope_id

        if memory_type is not None:
            filters.append("m.memory_type = :memory_type")
            parameters["memory_type"] = MemoryType(memory_type).value

        if not include_expired:
            filters.append(
                "(m.expires_at IS NULL OR m.expires_at > :now)"
            )
            parameters["now"] = (
                datetime.now(UTC)
                .replace(tzinfo=None)
                .isoformat(sep=" ")
            )

        statement = text(
            f"""
            SELECT
                m.id,
                m.memory_type,
                m.scope_id,
                m.title,
                m.content,
                m.summary,
                m.importance,
                m.confidence,
                m.source,
                m.expires_at,
                m.tags,
                m.created_at,
                m.updated_at,
                m.version,
                bm25(memories_fts, 2.0, 1.0, 0.5) AS fts_rank
            FROM memories_fts
            JOIN memories AS m
              ON m.rowid = memories_fts.rowid
            WHERE {" AND ".join(filters)}
            ORDER BY
                fts_rank ASC,
                m.importance DESC,
                m.updated_at DESC,
                m.id ASC
            LIMIT :limit
            """
        )

        rows = self.session.execute(statement, parameters).mappings()
        return [
            MemorySearchResult.model_validate(dict(row))
            for row in rows
        ]

    def list(
        self,
        *,
        scope_id: str | None = None,
        memory_type: MemoryType | str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Memory]:
        if not 1 <= limit <= 500:
            raise ValueError("limit must be between 1 and 500")
        if offset < 0:
            raise ValueError("offset cannot be negative")

        statement = select(MemoryRow).order_by(
            MemoryRow.updated_at.desc(),
            MemoryRow.id,
        )
        if scope_id is not None:
            statement = statement.where(
                MemoryRow.scope_id == scope_id
            )
        if memory_type is not None:
            statement = statement.where(
                MemoryRow.memory_type
                == MemoryType(memory_type).value
            )

        rows = self.session.execute(
            statement.limit(limit).offset(offset)
        ).scalars()
        return [self._to_memory(row) for row in rows]

    def _require_row(self, memory_id: str) -> MemoryRow:
        row = self.session.get(MemoryRow, memory_id)
        if row is None:
            raise MemoryNotFound(f"Memory not found: {memory_id}")
        return row

    def _redact_text(self, value: str) -> str:
        return str(self.redactor.redact(value))

    def _redact_optional_text(
        self,
        value: str | None,
    ) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            return None
        return self._redact_text(normalized)

    def _redact_tags(
        self,
        values: Sequence[str],
    ) -> _StringList:
        redacted: _StringList = []
        for value in values:
            normalized = value.strip()
            if not normalized:
                continue

            key, separator, _ = normalized.partition("=")
            if (
                separator
                and _SENSITIVE_TAG_KEY_PATTERN.fullmatch(key.strip())
            ):
                redacted.append("[REDACTED]")
            else:
                redacted.append(self._redact_text(normalized))
        return redacted

    @staticmethod
    def _required_text(
        value: str | None,
        field_name: str,
    ) -> str:
        if value is None:
            raise ValueError(f"{field_name} is required")
        normalized = value.strip()
        if not normalized:
            raise ValueError(f"{field_name} cannot be blank")
        return normalized

    @staticmethod
    def _required_number(
        value: float | None,
        field_name: str,
    ) -> float:
        if value is None:
            raise ValueError(f"{field_name} cannot be null")
        return value

    @staticmethod
    def _build_fts_query(query: str) -> str | None:
        tokens = _FTS_TOKEN_PATTERN.findall(query.casefold())
        if not tokens:
            return None

        escaped = [token.replace('"', '""') for token in tokens]
        return " OR ".join(f'"{token}"' for token in escaped)

    @staticmethod
    def _to_memory(row: MemoryRow) -> Memory:
        return Memory.model_validate(row)
