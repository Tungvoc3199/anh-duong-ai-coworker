from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from app.memory import (
    MemoryNotFound,
    MemoryRepository,
    MemoryType,
    MemoryUpdate,
)


@pytest.fixture
def memory_repository(migrated_engine) -> MemoryRepository:
    factory = sessionmaker(
        bind=migrated_engine,
        class_=Session,
        expire_on_commit=False,
        autoflush=False,
    )
    session = factory()
    repository = MemoryRepository(session)
    try:
        yield repository
        session.commit()
    finally:
        session.close()


def test_migration_creates_fts_table_and_sync_triggers(
    migrated_engine,
) -> None:
    expected = {
        "memories_fts": "table",
        "memories_fts_ai": "trigger",
        "memories_fts_ad": "trigger",
        "memories_fts_au": "trigger",
    }

    with migrated_engine.connect() as connection:
        rows = connection.execute(
            text(
                """
                SELECT name, type
                FROM sqlite_master
                WHERE name IN (
                    'memories_fts',
                    'memories_fts_ai',
                    'memories_fts_ad',
                    'memories_fts_au'
                )
                """
            )
        ).all()

    assert {name: object_type for name, object_type in rows} == expected


def test_fts_finds_memory_by_content(
    memory_repository: MemoryRepository,
) -> None:
    memory_repository.create(
        memory_type=MemoryType.PROJECT,
        scope_id="proj_1",
        title="Runtime",
        content="Tailscale chạy trên Windows host",
        importance=0.8,
        confidence=1.0,
    )

    results = memory_repository.search_fts(
        "Tailscale Windows",
        scope_id="proj_1",
    )

    assert results[0].title == "Runtime"
    assert results[0].scope_id == "proj_1"


def test_fts_filters_by_scope(
    memory_repository: MemoryRepository,
) -> None:
    memory_repository.create(
        memory_type=MemoryType.PROJECT,
        scope_id="proj_alpha",
        title="Alpha runtime",
        content="OpenClaw chạy bằng Docker Desktop",
    )
    memory_repository.create(
        memory_type=MemoryType.PROJECT,
        scope_id="proj_beta",
        title="Beta runtime",
        content="OpenClaw chạy bằng Docker Desktop",
    )

    results = memory_repository.search_fts(
        "OpenClaw Docker",
        scope_id="proj_beta",
    )

    assert [result.title for result in results] == ["Beta runtime"]


def test_fts_finds_memory_by_tags(
    memory_repository: MemoryRepository,
) -> None:
    memory_repository.create(
        memory_type=MemoryType.SEMANTIC,
        scope_id="global",
        title="Database rule",
        content="Database nằm trong Linux filesystem.",
        tags=("sqlite", "wal-mode", "wsl"),
    )

    results = memory_repository.search_fts(
        "wal mode",
        scope_id="global",
    )

    assert results[0].title == "Database rule"
    assert results[0].tags == ("sqlite", "wal-mode", "wsl")


def test_update_refreshes_fts_index(
    memory_repository: MemoryRepository,
) -> None:
    memory = memory_repository.create(
        memory_type=MemoryType.PROJECT,
        scope_id="proj_1",
        title="Old architecture",
        content="Runtime uses a manual process.",
    )

    memory_repository.update(
        memory.id,
        MemoryUpdate(
            title="New architecture",
            content="Runtime uses systemd background service.",
            tags=("systemd", "background"),
        ),
    )

    assert memory_repository.search_fts(
        "manual process",
        scope_id="proj_1",
    ) == []

    results = memory_repository.search_fts(
        "systemd background",
        scope_id="proj_1",
    )
    assert results[0].title == "New architecture"


def test_delete_removes_memory_from_fts(
    memory_repository: MemoryRepository,
) -> None:
    memory = memory_repository.create(
        memory_type=MemoryType.EPISODIC,
        scope_id="proj_1",
        title="Temporary failure",
        content="Gateway returned timeout during restart.",
    )

    assert memory_repository.delete(memory.id) is True

    assert memory_repository.search_fts(
        "Gateway timeout",
        scope_id="proj_1",
    ) == []
    assert memory_repository.delete(memory.id) is False


def test_get_missing_memory_raises(
    memory_repository: MemoryRepository,
) -> None:
    with pytest.raises(MemoryNotFound, match="mem_missing"):
        memory_repository.get("mem_missing")


def test_search_handles_punctuation_without_fts_syntax_error(
    memory_repository: MemoryRepository,
) -> None:
    memory_repository.create(
        memory_type=MemoryType.USER,
        scope_id="user",
        title="CLI preference",
        content="Lệnh phải ghi rõ PowerShell hoặc Ubuntu WSL.",
    )

    results = memory_repository.search_fts(
        'PowerShell + Ubuntu/WSL? "command"',
        scope_id="user",
    )

    assert results[0].title == "CLI preference"


def test_search_excludes_expired_memory_by_default(
    memory_repository: MemoryRepository,
) -> None:
    memory_repository.create(
        memory_type=MemoryType.SESSION,
        scope_id="session_1",
        title="Expired context",
        content="Temporary context about Telegram bot.",
        expires_at=datetime.now(UTC) - timedelta(minutes=1),
    )

    assert memory_repository.search_fts(
        "Telegram bot",
        scope_id="session_1",
    ) == []

    results = memory_repository.search_fts(
        "Telegram bot",
        scope_id="session_1",
        include_expired=True,
    )
    assert results[0].title == "Expired context"


def test_secret_redaction_runs_before_memory_is_stored(
    memory_repository: MemoryRepository,
) -> None:
    memory = memory_repository.create(
        memory_type=MemoryType.USER,
        scope_id="user",
        title="Provider configuration",
        content=(
            "OPENAI_API_KEY=sk-proj-1234567890abcdef "
            "provider is enabled"
        ),
        tags=("api_key=secret-value", "provider"),
    )

    loaded = memory_repository.get(memory.id)

    assert "sk-proj-1234567890abcdef" not in loaded.content
    assert "[REDACTED]" in loaded.content
    assert loaded.tags[0] == "[REDACTED]"


def test_empty_search_returns_no_results(
    memory_repository: MemoryRepository,
) -> None:
    assert memory_repository.search_fts(
        " + / ? ",
        scope_id="proj_1",
    ) == []
