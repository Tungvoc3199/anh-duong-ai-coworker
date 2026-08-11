from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, insert, select, update

from app.config import Settings
from app.db.base import Base
from app.db.models import AsyncTaskRunRow, ProjectRow, TaskRow
from app.db.session import create_db_engine
from app.main import create_app

TOKEN = "cancel-safety-token"


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    runtime_engine = create_db_engine(
        "sqlite+pysqlite:///"
        f"{tmp_path / 'cancel-safety.db'}"
    )
    Base.metadata.create_all(runtime_engine)
    with runtime_engine.begin() as connection:
        connection.execute(
            insert(ProjectRow).values(
                id="proj_cancel",
                name="Cancel Safety",
                slug="cancel-safety",
                status="active",
            )
        )
    try:
        yield runtime_engine
    finally:
        runtime_engine.dispose()


def _app(
    engine: Engine,
    tmp_path: Path,
) -> FastAPI:
    return create_app(
        settings=Settings(
            database_url="sqlite+pysqlite:///:memory:",
            audit_path=tmp_path / "cancel-audit.jsonl",
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
        "project_id": "proj_cancel",
        "title": f"Cancel safety {suffix}",
        "goal": "Exercise safe cancellation only.",
        "risk_level": 0,
        "workspace": str(tmp_path),
        "source_channel": "api",
        "idempotency_key": f"cancel-safety:{suffix}",
    }


def _set_state(
    engine: Engine,
    *,
    run_id: str,
    task_id: str,
    run_status: str,
    task_status: str,
) -> None:
    with engine.begin() as connection:
        connection.execute(
            update(AsyncTaskRunRow)
            .where(AsyncTaskRunRow.id == run_id)
            .values(status=run_status)
        )
        connection.execute(
            update(TaskRow)
            .where(TaskRow.id == task_id)
            .values(status=task_status)
        )


def _database_state(
    engine: Engine,
    *,
    run_id: str,
    task_id: str,
) -> tuple[str, int, str, int]:
    with engine.connect() as connection:
        run = connection.execute(
            select(
                AsyncTaskRunRow.status,
                AsyncTaskRunRow.version,
            ).where(AsyncTaskRunRow.id == run_id)
        ).one()
        task = connection.execute(
            select(
                TaskRow.status,
                TaskRow.version,
            ).where(TaskRow.id == task_id)
        ).one()
    return run.status, run.version, task.status, task.version


@pytest.mark.parametrize(
    ("run_status", "task_status"),
    (
        ("claimed", "queued"),
        ("running", "running"),
        ("verifying", "verifying"),
        ("completed", "completed"),
    ),
)
def test_cancel_rejects_active_and_completed_without_state_change(
    engine: Engine,
    tmp_path: Path,
    run_status: str,
    task_status: str,
) -> None:
    app = _app(engine, tmp_path)
    with TestClient(app) as client:
        created = client.post(
            "/api/async-tasks",
            headers=_headers(),
            json=_payload(tmp_path, run_status),
        ).json()
        _set_state(
            engine,
            run_id=created["run_id"],
            task_id=created["task_id"],
            run_status=run_status,
            task_status=task_status,
        )
        before = _database_state(
            engine,
            run_id=created["run_id"],
            task_id=created["task_id"],
        )

        response = client.post(
            f"/api/async-tasks/{created['run_id']}/cancel",
            headers=_headers(),
        )

        after = _database_state(
            engine,
            run_id=created["run_id"],
            task_id=created["task_id"],
        )

    assert response.status_code == 409
    assert after == before


@pytest.mark.parametrize(
    ("run_status", "task_status"),
    (
        ("pending", "queued"),
        ("retry_wait", "running"),
    ),
)
def test_cancel_immediately_cancels_only_safe_waiting_states(
    engine: Engine,
    tmp_path: Path,
    run_status: str,
    task_status: str,
) -> None:
    app = _app(engine, tmp_path)
    with TestClient(app) as client:
        created = client.post(
            "/api/async-tasks",
            headers=_headers(),
            json=_payload(tmp_path, run_status),
        ).json()
        _set_state(
            engine,
            run_id=created["run_id"],
            task_id=created["task_id"],
            run_status=run_status,
            task_status=task_status,
        )

        response = client.post(
            f"/api/async-tasks/{created['run_id']}/cancel",
            headers=_headers(),
        )

    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"
    state = _database_state(
        engine,
        run_id=created["run_id"],
        task_id=created["task_id"],
    )
    assert state[0] == "cancelled"
    assert state[2] == "cancelled"


def test_cancelled_run_is_idempotent_and_audited_once(
    engine: Engine,
    tmp_path: Path,
) -> None:
    app = _app(engine, tmp_path)
    with TestClient(app) as client:
        created = client.post(
            "/api/async-tasks",
            headers=_headers(),
            json=_payload(tmp_path, "idempotent"),
        ).json()
        first = client.post(
            f"/api/async-tasks/{created['run_id']}/cancel",
            headers=_headers(),
        )
        second = client.post(
            f"/api/async-tasks/{created['run_id']}/cancel",
            headers=_headers(),
        )

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json() == first.json()

    records = [
        json.loads(line)
        for line in (
            tmp_path / "cancel-audit.jsonl"
        ).read_text(encoding="utf-8").splitlines()
    ]
    cancelled_events = [
        record
        for record in records
        if record["event_type"] == "async_run.cancelled"
    ]
    assert len(cancelled_events) == 1
