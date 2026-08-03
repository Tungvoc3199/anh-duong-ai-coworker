from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, insert, select

from app.config import Settings
from app.db.base import Base
from app.db.models import AsyncTaskRunRow, ProjectRow, TaskRow
from app.db.session import create_db_engine
from app.main import create_app

TOKEN = "api-correction-token"


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    runtime_engine = create_db_engine(
        "sqlite+pysqlite:///"
        f"{tmp_path / 'api-corrections.db'}"
    )
    Base.metadata.create_all(runtime_engine)
    with runtime_engine.begin() as connection:
        connection.execute(
            insert(ProjectRow).values(
                id="proj_api_correction",
                name="API Correction",
                slug="api-correction",
                status="active",
            )
        )
    try:
        yield runtime_engine
    finally:
        runtime_engine.dispose()


def _app(engine: Engine, tmp_path: Path) -> FastAPI:
    return create_app(
        settings=Settings(
            database_url="sqlite+pysqlite:///:memory:",
            audit_path=tmp_path / "api-correction-audit.jsonl",
            internal_api_token=TOKEN,
            async_worker_enabled=False,
            async_worker_workspace_roots=(tmp_path,),
        ),
        engine=engine,
    )


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKEN}"}


def _payload(
    tmp_path: Path,
    suffix: str,
) -> dict[str, object]:
    return {
        "project_id": "proj_api_correction",
        "title": f"API correction {suffix}",
        "goal": "Validate corrected API behavior.",
        "risk_level": 0,
        "workspace": str(tmp_path),
        "source_channel": "api",
        "idempotency_key": f"api-correction:{suffix}",
    }


def _counts(engine: Engine) -> tuple[int, int]:
    with engine.connect() as connection:
        tasks = connection.scalar(
            select(func.count()).select_from(TaskRow)
        )
        runs = connection.scalar(
            select(func.count()).select_from(AsyncTaskRunRow)
        )
    assert tasks is not None
    assert runs is not None
    return tasks, runs


def test_list_filters_by_task_id(
    engine: Engine,
    tmp_path: Path,
) -> None:
    app = _app(engine, tmp_path)
    with TestClient(app) as client:
        first = client.post(
            "/api/async-tasks",
            headers=_headers(),
            json=_payload(tmp_path, "first"),
        ).json()
        client.post(
            "/api/async-tasks",
            headers=_headers(),
            json=_payload(tmp_path, "second"),
        )

        response = client.get(
            "/api/async-tasks",
            params={"task_id": first["task_id"]},
            headers=_headers(),
        )

    assert response.status_code == 200
    assert [run["id"] for run in response.json()] == [
        first["run_id"]
    ]
    assert {
        run["task_id"] for run in response.json()
    } == {first["task_id"]}


def test_post_rejects_when_runtime_is_not_accepting_tasks(
    engine: Engine,
    tmp_path: Path,
) -> None:
    app = _app(engine, tmp_path)
    with TestClient(app) as client:
        app.state.accepting_async_tasks = False
        before = _counts(engine)

        response = client.post(
            "/api/async-tasks",
            headers=_headers(),
            json=_payload(tmp_path, "shutdown"),
        )

        after = _counts(engine)

    assert response.status_code == 503
    assert response.json()["detail"] == (
        "Async task runtime is not accepting new tasks."
    )
    assert before == after == (0, 0)
