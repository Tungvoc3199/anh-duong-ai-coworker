from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import Engine, inspect

from alembic import command
from app.db.session import create_db_engine


@pytest.fixture
def migrated_engine(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[Engine]:
    database_path = tmp_path / "async-runner-schema.db"
    database_url = f"sqlite+pysqlite:///{database_path}"
    monkeypatch.setenv("ANH_DUONG_DATABASE_URL", database_url)

    config = Config("alembic.ini")
    command.upgrade(config, "head")

    engine = create_db_engine(database_url)
    try:
        yield engine
    finally:
        engine.dispose()


def test_async_task_runs_schema(migrated_engine: Engine) -> None:
    inspector = inspect(migrated_engine)
    assert "async_task_runs" in inspector.get_table_names()

    columns = {
        column["name"]
        for column in inspector.get_columns("async_task_runs")
    }
    assert {
        "id",
        "task_id",
        "status",
        "mode",
        "goal",
        "workspace",
        "request_json",
        "checkpoint_json",
        "result_json",
        "attempt",
        "max_attempts",
        "run_after",
        "lease_owner",
        "lease_expires_at",
        "idempotency_key",
        "external_run_id",
        "last_error_code",
        "last_error_message",
        "source_chat_id",
        "notification_status",
        "notification_attempts",
        "created_at",
        "updated_at",
        "version",
    } <= columns

    unique_sets = {
        tuple(sorted(item["column_names"]))
        for item in inspector.get_unique_constraints("async_task_runs")
    }
    assert ("idempotency_key",) in unique_sets
    assert ("task_id",) in unique_sets

    index_columns = {
        tuple(index["column_names"])
        for index in inspector.get_indexes("async_task_runs")
    }
    assert ("status",) in index_columns
    assert ("run_after",) in index_columns
    assert ("lease_expires_at",) in index_columns
    assert ("notification_status",) in index_columns
