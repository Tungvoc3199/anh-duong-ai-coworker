from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
from sqlalchemy.orm import Session, sessionmaker

from app.async_tasks import (
    AsyncRunStatus,
    AsyncTaskCreate,
    AsyncTaskPolicyGate,
    AsyncTaskRepository,
    AsyncTaskService,
    AsyncTaskWorker,
    NotificationStatus,
    NotificationWorker,
)
from app.audit import AuditWriter
from app.db.base import Base
from app.db.models import ProjectRow, TaskRow
from app.db.session import create_db_engine
from app.openclaw import OpenClawExecutor, OpenClawNotifier
from app.tasks import TaskRepository, TaskService, TaskStatus


def test_api_to_http_execution_to_http_notification(
    tmp_path: Path,
) -> None:
    engine = create_db_engine(f"sqlite+pysqlite:///{tmp_path / 'async-e2e.db'}")
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

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    paths: list[str] = []

    try:
        with factory() as session:
            audit_writer = AuditWriter(
                tmp_path / "e2e-audit.jsonl",
                fsync=False,
            )
            service = AsyncTaskService(
                task_service=TaskService(
                    TaskRepository(session),
                    audit_writer,
                ),
                repository=AsyncTaskRepository(session),
                policy_gate=AsyncTaskPolicyGate((tmp_path,)),
            )
            accepted = service.create(
                AsyncTaskCreate(
                    project_id="proj_e2e",
                    title="E2E async task",
                    goal="Complete through the HTTP gateway",
                    mode="build",
                    risk_level=0,
                    workspace=str(workspace),
                    source_channel="telegram",
                    source_chat_id="chat-test",
                    idempotency_key="telegram:e2e",
                )
            )
            session.commit()

        assert paths == []

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
                                                "outcome": ("completed"),
                                                "summary": "E2E done",
                                                "artifacts": [],
                                                "verification": ["mock verified"],
                                                "criterion_verification": [
                                                    {
                                                        "criterion": (
                                                            "Outcome achieved and verified: "
                                                            "Complete through the HTTP gateway"
                                                        ),
                                                        "status": "verified",
                                                        "evidence_refs": ["mock:e2e"],
                                                    }
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
            clock=lambda: datetime.now(UTC) + timedelta(seconds=1),
        )
        assert asyncio.run(worker.run_once()) is True
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
            assert asyncio.run(notification_worker.run_once()) is True
        finally:
            asyncio.run(notifier.aclose())

        with factory() as session:
            run = AsyncTaskRepository(session).get(accepted.run_id)
            task = session.get(
                TaskRow,
                accepted.task_id,
            )

        assert paths == ["/v1/responses", "/tools/invoke"]
        assert run.status is AsyncRunStatus.COMPLETED
        assert run.notification_status is NotificationStatus.SENT
        assert task is not None
        assert task.status == TaskStatus.COMPLETED.value
    finally:
        engine.dispose()
