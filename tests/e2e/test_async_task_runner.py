from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.async_tasks import (
    AsyncRunStatus,
    AsyncTaskPolicyGate,
    AsyncTaskRepository,
    AsyncTaskWorker,
    NotificationStatus,
    NotificationWorker,
)
from app.audit import AuditWriter
from app.config import Settings
from app.db.base import Base
from app.db.models import ProjectRow, TaskRow
from app.db.session import create_db_engine
from app.main import create_app
from app.openclaw import OpenClawExecutor, OpenClawNotifier
from app.tasks import TaskStatus


@pytest.mark.asyncio
async def test_api_to_http_execution_to_http_notification(
    tmp_path: Path,
) -> None:
    engine = create_db_engine(
        "sqlite+pysqlite:///"
        f"{tmp_path / 'async-e2e.db'}"
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(
        bind=engine,
        class_=Session,
        expire_on_commit=False,
        autoflush=False,
    )
    with factory() as session:
        session.add(
            ProjectRow(
                id="proj_e2e",
                name="E2E Project",
                slug="e2e-project",
                status="active",
            )
        )
        session.commit()

    settings = Settings(
        database_url="sqlite+pysqlite:///:memory:",
        audit_path=tmp_path / "e2e-audit.jsonl",
        internal_api_token="e2e-token",
        async_worker_enabled=False,
        async_worker_workspace_roots=(tmp_path,),
    )
    app = create_app(settings=settings, engine=engine)
    paths: list[str] = []

    try:
        with TestClient(app) as client:
            accepted = client.post(
                "/api/async-tasks",
                headers={
                    "Authorization": "Bearer e2e-token",
                },
                json={
                    "project_id": "proj_e2e",
                    "title": "E2E async task",
                    "goal": "Complete through the HTTP gateway",
                    "mode": "build",
                    "risk_level": 0,
                    "workspace": str(tmp_path / "workspace"),
                    "source_channel": "telegram",
                    "source_chat_id": "chat-test",
                    "idempotency_key": "telegram:e2e",
                },
            )

        assert accepted.status_code == 202
        assert paths == []
        accepted_body = accepted.json()

        def handler(request: httpx.Request) -> httpx.Response:
            paths.append(request.url.path)
            if request.url.path == "/v1/responses":
                return httpx.Response(
                    200,
                    json={
                        "id": "resp_e2e",
                        "output": [
                            {
                                "type": "message",
                                "content": [
                                    {
                                        "type": "output_text",
                                        "text": json.dumps(
                                            {
                                                "outcome": (
                                                    "completed"
                                                ),
                                                "summary": "E2E done",
                                                "artifacts": [],
                                                "verification": [
                                                    "mock verified"
                                                ],
                                            }
                                        ),
                                    }
                                ],
                            }
                        ],
                    },
                )
            if request.url.path == "/tools/invoke":
                return httpx.Response(
                    200,
                    json={
                        "ok": True,
                        "result": {"messageId": "e2e-message"},
                    },
                )
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        executor = OpenClawExecutor(
            base_url="http://127.0.0.1:18789",
            auth_token="fake-gateway-token",
            transport=transport,
        )
        worker = AsyncTaskWorker(
            session_factory=factory,
            audit_writer=AuditWriter(
                tmp_path / "e2e-audit.jsonl",
                fsync=False,
            ),
            policy_gate=AsyncTaskPolicyGate((tmp_path,)),
            executor=executor,
            worker_id="e2e-worker",
            lease_seconds=900,
            clock=lambda: (
                datetime.now(UTC) + timedelta(seconds=1)
            ),
        )
        assert await worker.run_once() is True
        assert paths == ["/v1/responses"]

        notifier = OpenClawNotifier(
            base_url="http://127.0.0.1:18789",
            auth_token="fake-gateway-token",
            transport=transport,
        )
        notification_worker = NotificationWorker(
            session_factory=factory,
            notifier=notifier,
        )
        try:
            assert await notification_worker.run_once() is True
        finally:
            await notifier.aclose()

        with factory() as session:
            run = AsyncTaskRepository(session).get(
                accepted_body["run_id"]
            )
            task = session.get(
                TaskRow,
                accepted_body["task_id"],
            )

        assert paths == ["/v1/responses", "/tools/invoke"]
        assert run.status is AsyncRunStatus.COMPLETED
        assert run.notification_status is NotificationStatus.SENT
        assert task is not None
        assert task.status == TaskStatus.COMPLETED.value
    finally:
        engine.dispose()
