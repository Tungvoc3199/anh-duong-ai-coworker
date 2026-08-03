from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, cast

import httpx
import pytest

from app.async_tasks import (
    AsyncRunStatus,
    AsyncTaskMode,
    AsyncTaskRun,
    NotificationStatus,
)
from app.openclaw import (
    OpenClawNotifier,
    OpenClawTransportError,
)


def _run() -> AsyncTaskRun:
    now = datetime(2026, 7, 27, 22, 0, tzinfo=UTC)
    return AsyncTaskRun(
        id="run_1",
        task_id="task_1",
        status=AsyncRunStatus.COMPLETED,
        mode=AsyncTaskMode.BUILD,
        goal="Complete the task",
        workspace="/mnt/f/AIOS/anh-duong-core",
        request_json="{}",
        checkpoint_json=None,
        result_json=json.dumps(
            {
                "outcome": "completed",
                "summary": "Task completed. DR1R-F1-TEST",
                "artifacts": ["artifact.zip"],
                "verification": ["pytest passed"],
            }
        ),
        attempt=1,
        max_attempts=3,
        run_after=now,
        lease_owner=None,
        lease_expires_at=None,
        idempotency_key="telegram:1",
        external_run_id="resp_1",
        last_error_code=None,
        last_error_message=None,
        source_chat_id="chat-test",
        notification_status=NotificationStatus.PENDING,
        notification_attempts=0,
        created_at=now,
        updated_at=now,
        version=3,
    )


@pytest.mark.asyncio
async def test_notifier_invokes_message_tool_for_telegram() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["json"] = json.loads(request.content)
        captured["authorization"] = request.headers.get(
            "authorization"
        )
        return httpx.Response(
            200,
            json={"ok": True, "result": {"messageId": "42"}},
        )

    notifier = OpenClawNotifier(
        base_url="http://127.0.0.1:18789",
        notification_path="/tools/invoke",
        auth_token="test-token",
        transport=httpx.MockTransport(handler),
    )

    await notifier.send_final(_run())

    payload = cast(dict[str, Any], captured["json"])
    args = cast(dict[str, Any], payload["args"])
    assert captured["path"] == "/tools/invoke"
    assert captured["authorization"] == "Bearer test-token"
    assert payload["tool"] == "message"
    assert payload["idempotencyKey"] == "notify:run_1:completed"
    assert args["action"] == "send"
    assert args["channel"] == "telegram"
    assert args["target"] == "chat-test"
    assert args["idempotencyKey"] == "notify:run_1:completed"
    message = cast(str, args["message"])
    assert "Task completed. DR1R-F1-TEST" in message
    assert "DR1R-F1-TEST" in message
    assert _run().task_id not in message
    assert "task_" not in message
    assert "run_" not in message


@pytest.mark.asyncio
async def test_notifier_classifies_service_unavailable_as_retryable() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            503,
            json={"ok": False, "error": {"message": "unavailable"}},
        )

    notifier = OpenClawNotifier(
        base_url="http://127.0.0.1:18789",
        notification_path="/tools/invoke",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(OpenClawTransportError) as captured:
        await notifier.send_final(_run())

    assert captured.value.retryable is True
    assert captured.value.code == "gateway_unavailable"
