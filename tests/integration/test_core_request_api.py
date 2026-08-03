from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, insert, select
from sqlalchemy.orm import Session

import app.main as main_module
from app.config import Settings
from app.db.models import AsyncTaskRunRow, ProjectRow, TaskRow
from app.main import create_app
from app.memory import MemoryRepository, MemoryType

TOKEN = "or1-internal-token"


def _settings(tmp_path: Path, *, token: str | None = TOKEN) -> Settings:
    return Settings(
        _env_file=None,
        database_url=f"sqlite+pysqlite:///{tmp_path / 'unused.db'}",
        audit_path=tmp_path / "or1-audit.jsonl",
        internal_api_token=token,
        async_worker_enabled=False,
    )


def _headers(token: str = TOKEN) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _seed_registry(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.execute(
            insert(ProjectRow),
            [
                {
                    "id": "proj_or1",
                    "name": "OR-1 Project",
                    "slug": "or1-project",
                    "status": "active",
                    "priority": "high",
                    "current_phase": "OR-1",
                    "summary": "Build the Core Request Pipeline.",
                    "constraints": ["No execution"],
                },
                {
                    "id": "proj_other",
                    "name": "Other Project",
                    "slug": "other-project",
                    "status": "active",
                    "priority": "normal",
                    "current_phase": None,
                    "summary": None,
                    "constraints": [],
                },
            ],
        )
        connection.execute(
            insert(TaskRow).values(
                id="task_or1",
                project_id="proj_or1",
                title="Build OR-1",
                description="Prepare requests only.",
                status="planning",
                priority="high",
                risk_level=0,
                requested_by="user",
                source_channel="internal",
                approval_required=False,
            )
        )


def test_prepare_returns_200_writes_minimal_audit_and_creates_no_async_run(
    migrated_engine: Engine,
    tmp_path: Path,
) -> None:
    _seed_registry(migrated_engine)
    settings = _settings(tmp_path)
    app = create_app(settings=settings, engine=migrated_engine)

    with TestClient(app) as client:
        response = client.post(
            "/api/internal/requests/prepare",
            headers=_headers(),
            json={
                "text": "Xin chào!",
                "request_id": "req_api_1",
                "actor": "desktop",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["request_id"] == "req_api_1"
    assert payload["normalized_text"] == "Xin chào!"
    assert payload["persona"]["version"] == "1.0"
    assert len(payload["persona"]["content_hash"]) == 64
    assert payload["route_decision"]["route"] == "direct"
    assert (
        payload["capability_decision"]["capability"]
        == "conversational_response"
    )
    assert payload["execution_required"] is False
    assert payload["created_at"].endswith("Z")

    with migrated_engine.connect() as connection:
        run_count = connection.execute(
            select(func.count()).select_from(AsyncTaskRunRow)
        ).scalar_one()
    assert run_count == 0

    records = [
        json.loads(line)
        for line in settings.audit_path.read_text(encoding="utf-8").splitlines()
    ]
    event = records[-1]
    assert event["event_type"] == "request.prepared"
    assert set(event["payload"]) == {
        "capability",
        "channel",
        "persona_content_hash",
        "persona_version",
        "project_id",
        "request_id",
        "route",
        "task_id",
        "token_estimate",
        "warning_count",
    }


def test_prepare_reads_project_and_task_and_maps_registry_errors(
    migrated_engine: Engine,
    tmp_path: Path,
) -> None:
    _seed_registry(migrated_engine)
    app = create_app(
        settings=_settings(tmp_path),
        engine=migrated_engine,
    )

    with TestClient(app) as client:
        project = client.post(
            "/api/internal/requests/prepare",
            headers=_headers(),
            json={
                "text": "Tiến độ Project OR-1 thế nào?",
                "project_id": "proj_or1",
            },
        )
        task = client.post(
            "/api/internal/requests/prepare",
            headers=_headers(),
            json={
                "text": "Task OR-1 đang ở trạng thái nào?",
                "project_id": "proj_or1",
                "task_id": "task_or1",
            },
        )
        missing_project = client.post(
            "/api/internal/requests/prepare",
            headers=_headers(),
            json={
                "text": "Xem trạng thái Project missing.",
                "project_id": "proj_missing",
            },
        )
        missing_task = client.post(
            "/api/internal/requests/prepare",
            headers=_headers(),
            json={
                "text": "Xem trạng thái Task missing.",
                "task_id": "task_missing",
            },
        )
        mismatch = client.post(
            "/api/internal/requests/prepare",
            headers=_headers(),
            json={
                "text": "Xem trạng thái Task OR-1.",
                "project_id": "proj_other",
                "task_id": "task_or1",
            },
        )

    assert project.status_code == 200
    assert project.json()["project_id"] == "proj_or1"
    assert "identity: proj_or1" in project.json()["context"]["rendered_context"]
    assert task.status_code == 200
    assert task.json()["task_id"] == "task_or1"
    assert "identity: task_or1" in task.json()["context"]["rendered_context"]
    assert missing_project.status_code == 404
    assert missing_project.json()["detail"] == "Project not found: proj_missing"
    assert missing_task.status_code == 404
    assert missing_task.json()["detail"] == "Task not found: task_missing"
    assert mismatch.status_code == 409
    assert "Task/project context mismatch" in mismatch.json()["detail"]


def test_prepare_memory_request_uses_production_hybrid_retriever(
    migrated_engine: Engine,
    tmp_path: Path,
) -> None:
    with Session(migrated_engine) as session:
        MemoryRepository(session).create(
            memory_type=MemoryType.PROJECT,
            scope_id="scope_or1",
            title="Hybrid pipeline evidence",
            content="OR-1 production wiring uses Hybrid Memory Retriever.",
            importance=0.9,
            confidence=1.0,
            source="integration-test",
        )
        session.commit()
    app = create_app(
        settings=_settings(tmp_path),
        engine=migrated_engine,
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/internal/requests/prepare",
            headers=_headers(),
            json={
                "text": "Tìm trong bộ nhớ hybrid pipeline evidence.",
                "memory_scope_id": "scope_or1",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["route_decision"]["route"] == "memory"
    assert payload["capability_decision"]["capability"] == "memory_search"
    assert (
        "OR-1 production wiring uses Hybrid Memory Retriever."
        in payload["context"]["rendered_context"]
    )


def test_prepare_validation_auth_and_health_are_fail_closed_and_independent(
    migrated_engine: Engine,
    tmp_path: Path,
) -> None:
    app = create_app(
        settings=_settings(tmp_path),
        engine=migrated_engine,
    )

    with TestClient(app) as client:
        missing_auth = client.post(
            "/api/internal/requests/prepare",
            json={"text": "Xin chào!"},
        )
        invalid_auth = client.post(
            "/api/internal/requests/prepare",
            headers=_headers("wrong"),
            json={"text": "Xin chào!"},
        )
        blank = client.post(
            "/api/internal/requests/prepare",
            headers=_headers(),
            json={"text": " \n\t "},
        )
        health = client.get("/health")
        ready = client.get("/ready")

    assert missing_auth.status_code == 401
    assert invalid_auth.status_code == 401
    assert blank.status_code == 422
    assert health.status_code == 200
    assert ready.status_code == 200

    unconfigured = create_app(
        settings=_settings(tmp_path, token=None),
        engine=migrated_engine,
    )
    with TestClient(unconfigured) as client:
        unavailable = client.post(
            "/api/internal/requests/prepare",
            headers=_headers(),
            json={"text": "Xin chào!"},
        )
        health_without_token = client.get("/health")
        ready_without_token = client.get("/ready")

    assert unavailable.status_code == 503
    assert health_without_token.status_code == 200
    assert ready_without_token.status_code == 200


def test_prepare_response_redacts_secret(
    migrated_engine: Engine,
    tmp_path: Path,
) -> None:
    _seed_registry(migrated_engine)
    app = create_app(
        settings=_settings(tmp_path),
        engine=migrated_engine,
    )
    secret = "WR1_TEST_SECRET_MARKER"

    with TestClient(app) as client:
        response = client.post(
            "/api/internal/requests/prepare",
            headers=_headers(),
                json={
                    "text": f"Tạo file với api_key={secret}",
                    "project_id": "proj_or1",
                },
        )

    assert response.status_code == 200
    assert secret not in response.text
    assert "[REDACTED]" in response.text


def test_create_app_registers_pipeline_factory_without_invoking_it(
    monkeypatch,
    tmp_path: Path,
) -> None:
    calls: list[object] = []

    def recording_factory(*args: object, **kwargs: object) -> object:
        calls.append((args, kwargs))
        raise AssertionError("Pipeline factory must not run during app creation")

    monkeypatch.setattr(
        main_module,
        "create_core_request_pipeline",
        recording_factory,
    )

    application = main_module.create_app(settings=_settings(tmp_path))

    assert callable(application.state.core_request_pipeline_factory)
    assert calls == []
