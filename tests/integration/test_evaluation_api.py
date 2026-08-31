from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.base import Base
from app.db.models import AsyncTaskRunRow, TaskRow, WorkflowRow
from app.db.session import create_db_engine
from app.main import create_app

TOKEN = "evaluation-internal-token"
NOW = datetime(2026, 8, 31, 6, 0, tzinfo=UTC)


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    runtime_engine = create_db_engine(f"sqlite+pysqlite:///{tmp_path / 'evaluation-api.db'}")
    Base.metadata.create_all(runtime_engine)
    try:
        yield runtime_engine
    finally:
        runtime_engine.dispose()


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        database_url=f"sqlite+pysqlite:///{tmp_path / 'unused.db'}",
        audit_path=tmp_path / "audit.jsonl",
        internal_api_token=TOKEN,
        async_worker_enabled=False,
        async_worker_workspace_roots=(tmp_path,),
    )


def _headers(token: str = TOKEN) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _seed(engine: Engine) -> str:
    task_id = "task_eval_api"
    run_id = "run_eval_api"
    with Session(engine) as session:
        session.add(
            TaskRow(
                id=task_id,
                title="private title",
                description="private goal text",
                status="completed",
                priority="normal",
                risk_level=0,
                requested_by="user",
                source_channel="telegram",
                approval_required=False,
                created_at=NOW,
                updated_at=NOW + timedelta(seconds=12),
            )
        )
        session.flush()
        session.add(
            AsyncTaskRunRow(
                id=run_id,
                task_id=task_id,
                status="completed",
                mode="quick",
                goal="private goal text",
                request_json='{"private":"request"}',
                result_json='{"private":"result"}',
                attempt=1,
                max_attempts=3,
                run_after=NOW,
                idempotency_key="eval-api-idem",
                notification_status="sent",
                notification_attempts=1,
                created_at=NOW,
                updated_at=NOW + timedelta(seconds=12),
            )
        )
        session.add(
            WorkflowRow(
                id=run_id,
                task_id=task_id,
                status="pending",
                context_payload={},
                plan_payload={
                    "revision": 1,
                    "nodes": [
                        {
                            "id": "execute",
                            "capability_requirements": ["system_operation"],
                        }
                    ],
                    "node_executions": [],
                    "execution_budget": {"retries_used": 0},
                    "outcome_judgement": {
                        "disposition": "satisfied",
                        "criteria": [
                            {"satisfied": True, "status": "verified"}
                        ],
                    },
                },
                created_at=NOW,
                updated_at=NOW + timedelta(seconds=12),
            )
        )
        session.commit()
    return run_id


def test_evaluation_endpoints_require_internal_bearer(engine: Engine, tmp_path: Path) -> None:
    app = create_app(settings=_settings(tmp_path), engine=engine)
    with TestClient(app) as client:
        missing = client.get("/api/internal/evaluation/system")
        invalid = client.get(
            "/api/internal/evaluation/system",
            headers=_headers("wrong"),
        )

    assert missing.status_code == 401
    assert invalid.status_code == 401


def test_goal_and_system_endpoints_project_durable_state(engine: Engine, tmp_path: Path) -> None:
    run_id = _seed(engine)
    app = create_app(settings=_settings(tmp_path), engine=engine)
    with TestClient(app) as client:
        goal = client.get(
            f"/api/internal/evaluation/goals/{run_id}",
            headers=_headers(),
        )
        system = client.get(
            "/api/internal/evaluation/system",
            headers=_headers(),
        )

    assert goal.status_code == 200
    goal_payload = goal.json()
    assert goal_payload["run_id"] == run_id
    assert goal_payload["status"] == "completed"
    assert goal_payload["metrics"]["outcome"]["value"] == "success"
    assert "private goal text" not in goal.text
    assert system.status_code == 200
    assert system.json()["population"]["terminal_goals"] == 1
    assert system.json()["metrics"]["autonomous_completion_rate"]["value"] == 1.0


def test_missing_goal_returns_404_without_leaking_details(engine: Engine, tmp_path: Path) -> None:
    app = create_app(settings=_settings(tmp_path), engine=engine)
    with TestClient(app) as client:
        response = client.get(
            "/api/internal/evaluation/goals/run_missing",
            headers=_headers(),
        )

    assert response.status_code == 404
    assert response.json() == {"detail": "Goal telemetry not found."}
