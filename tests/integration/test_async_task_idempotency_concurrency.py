from __future__ import annotations

import asyncio
import threading
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import Engine, func, insert, select

from app.async_tasks import AsyncTaskRepository, AsyncTaskRun
from app.config import Settings
from app.db.base import Base
from app.db.models import AsyncTaskRunRow, ProjectRow, TaskRow
from app.db.session import create_db_engine
from app.main import create_app

TOKEN = "concurrent-idempotency-token"


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    runtime_engine = create_db_engine(
        "sqlite+pysqlite:///"
        f"{tmp_path / 'concurrent-idempotency.db'}"
    )
    Base.metadata.create_all(runtime_engine)
    with runtime_engine.begin() as connection:
        connection.execute(
            insert(ProjectRow).values(
                id="proj_concurrent",
                name="Concurrent Idempotency",
                slug="concurrent-idempotency",
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
            audit_path=tmp_path / "concurrent-audit.jsonl",
            internal_api_token=TOKEN,
            async_worker_enabled=False,
            async_worker_workspace_roots=(tmp_path,),
        ),
        engine=engine,
    )


def _payload(tmp_path: Path) -> dict[str, object]:
    return {
        "project_id": "proj_concurrent",
        "title": "Concurrent idempotency",
        "goal": "Create exactly one Task and one Run.",
        "risk_level": 0,
        "workspace": str(tmp_path),
        "source_channel": "api",
        "idempotency_key": "concurrent:same-key",
    }


@pytest.mark.asyncio
async def test_two_concurrent_requests_create_one_task_and_run(
    engine: Engine,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_lookup = (
        AsyncTaskRepository.get_by_idempotency_key
    )
    barrier = threading.Barrier(2)
    seen_sessions: set[int] = set()
    seen_lock = threading.Lock()

    def synchronized_lookup(
        repository: AsyncTaskRepository,
        key: str,
    ) -> AsyncTaskRun | None:
        result = original_lookup(repository, key)
        session_id = id(repository.session)
        with seen_lock:
            first_lookup = session_id not in seen_sessions
            seen_sessions.add(session_id)
        if first_lookup:
            try:
                barrier.wait(timeout=1)
            except threading.BrokenBarrierError:
                pass
        return result

    monkeypatch.setattr(
        AsyncTaskRepository,
        "get_by_idempotency_key",
        synchronized_lookup,
    )

    app = _app(engine, tmp_path)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            responses = await asyncio.gather(
                client.post(
                    "/api/async-tasks",
                    headers={
                        "Authorization": f"Bearer {TOKEN}"
                    },
                    json=_payload(tmp_path),
                ),
                client.post(
                    "/api/async-tasks",
                    headers={
                        "Authorization": f"Bearer {TOKEN}"
                    },
                    json=_payload(tmp_path),
                ),
            )

    assert [response.status_code for response in responses] == [
        202,
        202,
    ]
    payloads = [response.json() for response in responses]
    assert payloads[0]["task_id"] == payloads[1]["task_id"]
    assert payloads[0]["run_id"] == payloads[1]["run_id"]
    assert {payload["replayed"] for payload in payloads} == {
        False,
        True,
    }

    with engine.connect() as connection:
        task_count = connection.scalar(
            select(func.count()).select_from(TaskRow)
        )
        run_count = connection.scalar(
            select(func.count()).select_from(AsyncTaskRunRow)
        )
        run_task_id = connection.execute(
            select(AsyncTaskRunRow.task_id)
        ).scalar_one()

    assert task_count == 1
    assert run_count == 1
    assert run_task_id == responses[0].json()["task_id"]
