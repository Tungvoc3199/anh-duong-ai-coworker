"""RED tests: generic async-task API rejects ungoverned coding shapes (AD-L5-05).

A CODE_OPERATION-shaped submission without a typed ``governed_coding``
assignment must be rejected at the generic ``/api/async-tasks`` endpoint so
coding can only enter through the governed path.
"""
from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, insert

from app.config import Settings
from app.db.base import Base
from app.db.models import ProjectRow
from app.db.session import create_db_engine
from app.main import create_app

TOKEN = "internal-test-token"

_CODE_OPERATION_GOALS = (
    "Sửa code trong dự án và chạy kiểm thử.",
    "Refactor the module and update its unit tests.",
    "Implement a new feature in app/ with tests.",
    "Fix the bug in src/parser.py.",
)


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    runtime_engine = create_db_engine(
        "sqlite+pysqlite:///" f"{tmp_path / 'governed-api.db'}"
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


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        database_url=(
            "sqlite+pysqlite:///" f"{tmp_path / 'unused.db'}"
        ),
        audit_path=tmp_path / "api-audit.jsonl",
        internal_api_token=TOKEN,
        async_worker_enabled=False,
        async_worker_workspace_roots=(tmp_path,),
    )


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKEN}"}


def _payload(tmp_path: Path, goal: str) -> dict[str, object]:
    return {
        "project_id": "proj_api",
        "title": "Ungoverned coding attempt",
        "goal": goal,
        "mode": "build",
        "risk_level": 0,
        "workspace": str(tmp_path / "workspace"),
        "source_channel": "api",
        "idempotency_key": "api:ungoverned-coding-1",
    }


@pytest.mark.parametrize("goal", _CODE_OPERATION_GOALS)
def test_generic_endpoint_rejects_code_operation_without_assignment(
    engine: Engine,
    tmp_path: Path,
    goal: str,
) -> None:
    app = create_app(settings=_settings(tmp_path), engine=engine)
    with TestClient(app) as client:
        response = client.post(
            "/api/async-tasks",
            headers=_headers(),
            json=_payload(tmp_path, goal),
        )

    assert response.status_code == 422
    assert "governed_coding" in response.text


def test_generic_endpoint_still_accepts_non_coding_task(
    engine: Engine,
    tmp_path: Path,
) -> None:
    app = create_app(settings=_settings(tmp_path), engine=engine)
    with TestClient(app) as client:
        response = client.post(
            "/api/async-tasks",
            headers=_headers(),
            json={
                "project_id": "proj_api",
                "title": "Research task",
                "goal": "Tóm tắt các bài viết công khai của trang Facebook.",
                "mode": "build",
                "risk_level": 0,
                "workspace": str(tmp_path / "workspace"),
                "source_channel": "api",
                "idempotency_key": "api:research-1",
            },
        )

    assert response.status_code == 202


def test_governed_coding_submission_is_accepted_by_generic_endpoint(
    engine: Engine,
    tmp_path: Path,
) -> None:
    assignment = {
        "checkpoint_id": "AD-L5-05",
        "correlation_id": "req_api_gov_1",
        "workspace": str(
            tmp_path / "anh-duong-core.worktrees" / "api-gov"
        ),
        "manifest_digest": "c" * 64,
        "allowed_paths": ["app/"],
        "reviewer_required": True,
        "approval_required": False,
        "max_semantic_repair_rounds": 2,
    }
    app = create_app(settings=_settings(tmp_path), engine=engine)
    with TestClient(app) as client:
        response = client.post(
            "/api/async-tasks",
            headers=_headers(),
            json={
                **_payload(
                    tmp_path,
                    "Implement a new feature in app/ with tests.",
                ),
                "idempotency_key": "api:governed-api-1",
                "governed_coding": assignment,
            },
        )

    assert response.status_code == 202
