from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, insert, update

from app.config import Settings
from app.db.base import Base
from app.db.models import AsyncTaskRunRow, ProjectRow, TaskRow
from app.db.session import create_db_engine
from app.main import create_app

TOKEN = "internal-test-token"


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    runtime_engine = create_db_engine(
        "sqlite+pysqlite:///"
        f"{tmp_path / 'async-api.db'}"
    )
    Base.metadata.create_all(runtime_engine)
    with runtime_engine.begin() as connection:
        connection.execute(
            insert(ProjectRow).values(
                id="proj_api",
                name="API Project",
                slug="api-project",
                status="active",
            )
        )
    try:
        yield runtime_engine
    finally:
        runtime_engine.dispose()


def _settings(
    tmp_path: Path,
    *,
    token: str | None = TOKEN,
) -> Settings:
    return Settings(
        database_url=(
            "sqlite+pysqlite:///"
            f"{tmp_path / 'unused.db'}"
        ),
        audit_path=tmp_path / "api-audit.jsonl",
        internal_api_token=token,
        async_worker_enabled=False,
        async_worker_workspace_roots=(tmp_path,),
    )


def _headers(token: str = TOKEN) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _payload(tmp_path: Path) -> dict[str, object]:
    return {
        "project_id": "proj_api",
        "title": "Async API test",
        "goal": "Return immediately without executing inline",
        "mode": "build",
        "risk_level": 0,
        "workspace": str(tmp_path / "workspace"),
        "source_channel": "api",
        "idempotency_key": "api:request-1",
    }


def test_create_returns_202_and_duplicate_returns_same_run(
    engine: Engine,
    tmp_path: Path,
) -> None:
    app = create_app(
        settings=_settings(tmp_path),
        engine=engine,
    )
    with TestClient(app) as client:
        first = client.post(
            "/api/async-tasks",
            headers=_headers(),
            json=_payload(tmp_path),
        )
        second = client.post(
            "/api/async-tasks",
            headers=_headers(),
            json=_payload(tmp_path),
        )

    assert first.status_code == 202
    assert second.status_code == 202
    first_payload = first.json()
    second_payload = second.json()
    assert first_payload["task_id"] == second_payload["task_id"]
    assert first_payload["run_id"] == second_payload["run_id"]
    assert first_payload["status"] == second_payload["status"]
    assert first_payload["replayed"] is False
    assert second_payload["replayed"] is True
    assert first.json()["status"] == "pending"


def test_get_and_list_require_valid_bearer_auth(
    engine: Engine,
    tmp_path: Path,
) -> None:
    app = create_app(
        settings=_settings(tmp_path),
        engine=engine,
    )
    with TestClient(app) as client:
        created = client.post(
            "/api/async-tasks",
            headers=_headers(),
            json=_payload(tmp_path),
        ).json()
        missing = client.get(
            f"/api/async-tasks/{created['run_id']}"
        )
        invalid = client.get(
            "/api/async-tasks",
            headers=_headers("wrong-token"),
        )
        found = client.get(
            f"/api/async-tasks/{created['run_id']}",
            headers=_headers(),
        )
        listed = client.get(
            "/api/async-tasks",
            headers=_headers(),
        )

    assert missing.status_code == 401
    assert invalid.status_code == 401
    assert found.status_code == 200
    assert found.json()["id"] == created["run_id"]
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [
        created["run_id"]
    ]


def test_missing_internal_auth_config_fails_closed(
    engine: Engine,
    tmp_path: Path,
) -> None:
    app = create_app(
        settings=_settings(tmp_path, token=None),
        engine=engine,
    )
    with TestClient(app) as client:
        response = client.get(
            "/api/async-tasks",
            headers=_headers(),
        )

    assert response.status_code == 503
    assert response.json()["detail"] == (
        "Internal API authentication is not configured."
    )


def test_retry_failed_run_and_cancel_pending_run(
    engine: Engine,
    tmp_path: Path,
) -> None:
    app = create_app(
        settings=_settings(tmp_path),
        engine=engine,
    )
    with TestClient(app) as client:
        failed = client.post(
            "/api/async-tasks",
            headers=_headers(),
            json=_payload(tmp_path),
        ).json()
        with engine.begin() as connection:
            connection.execute(
                update(AsyncTaskRunRow)
                .where(
                    AsyncTaskRunRow.id == failed["run_id"]
                )
                .values(status="failed")
            )
            connection.execute(
                update(TaskRow)
                .where(TaskRow.id == failed["task_id"])
                .values(status="failed")
            )

        retried = client.post(
            f"/api/async-tasks/{failed['run_id']}/retry",
            headers=_headers(),
        )

        second_payload = _payload(tmp_path)
        second_payload["idempotency_key"] = "api:request-2"
        pending = client.post(
            "/api/async-tasks",
            headers=_headers(),
            json=second_payload,
        ).json()
        cancelled = client.post(
            f"/api/async-tasks/{pending['run_id']}/cancel",
            headers=_headers(),
        )

    assert retried.status_code == 200
    assert retried.json()["status"] == "pending"
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"


def test_cancel_completed_returns_conflict(
    engine: Engine,
    tmp_path: Path,
) -> None:
    app = create_app(
        settings=_settings(tmp_path),
        engine=engine,
    )
    with TestClient(app) as client:
        created = client.post(
            "/api/async-tasks",
            headers=_headers(),
            json=_payload(tmp_path),
        ).json()
        with engine.begin() as connection:
            connection.execute(
                update(AsyncTaskRunRow)
                .where(
                    AsyncTaskRunRow.id == created["run_id"]
                )
                .values(status="completed")
            )
            connection.execute(
                update(TaskRow)
                .where(TaskRow.id == created["task_id"])
                .values(status="completed")
            )

        response = client.post(
            f"/api/async-tasks/{created['run_id']}/cancel",
            headers=_headers(),
        )

    assert response.status_code == 409


def test_resolve_latest_approval_is_scoped_and_resumes_same_run(
    engine: Engine,
    tmp_path: Path,
) -> None:
    app = create_app(settings=_settings(tmp_path), engine=engine)
    payload = _payload(tmp_path)
    payload.update({
        "goal": "Publish the image to Facebook",
        "risk_level": 2,
        "approval_required": True,
        "workspace": str(tmp_path),
        "source_channel": "telegram",
        "source_chat_id": "chat-api",
        "source_session_id": "session-api",
        "source_message_id": "message-api",
        "idempotency_key": "telegram:message-api",
    })
    with TestClient(app) as client:
        created = client.post("/api/async-tasks", headers=_headers(), json=payload)
        resolved = client.post(
            "/api/async-tasks/approvals/resolve-latest",
            headers=_headers(),
            json={
                "source_chat_id": "chat-api",
                "source_session_id": "session-api",
                "resolved_by": "telegram:owner",
                "approved": True,
            },
        )
        replay = client.post(
            "/api/async-tasks/approvals/resolve-latest",
            headers=_headers(),
            json={
                "source_chat_id": "chat-api",
                "source_session_id": "session-api",
                "resolved_by": "telegram:owner",
                "approved": True,
            },
        )

    assert created.status_code == 202
    assert resolved.status_code == 200
    assert resolved.json()["id"] == created.json()["run_id"]
    assert resolved.json()["status"] == "pending"
    assert replay.status_code == 409
