from __future__ import annotations

import re

from app.async_tasks import AsyncTaskCreate
from app.openclaw.models import OpenClawExecutionRequest
from app.orchestration.models import CoreRequest
from app.orchestration.workflow import WorkflowResolver
from app.privacy.minimization import (
    content_fingerprint,
    minimize_async_request_payload,
    telegram_idempotency_key,
)


def test_telegram_idempotency_key_never_embeds_routing_identifiers() -> None:
    key = telegram_idempotency_key(
        source_chat_id="7535966424",
        source_message_id="message-99",
    )

    assert re.fullmatch(r"telegram:[0-9a-f]{64}", key)
    assert "7535966424" not in key
    assert "message-99" not in key
    assert key == telegram_idempotency_key(
        source_chat_id="7535966424",
        source_message_id="message-99",
    )


def test_minimize_async_request_payload_removes_telegram_routing_ids() -> None:
    request = AsyncTaskCreate(
        project_id="proj_1",
        title="Privacy test",
        goal="Summarize a user message",
        source_channel="telegram",
        source_chat_id="chat-secret",
        source_session_id="session-secret",
        source_message_id="message-secret",
        idempotency_key="telegram:already-pseudonymous",
    )

    payload = minimize_async_request_payload(request.model_dump(mode="json"))

    assert payload["source_chat_id"] is None
    assert payload["source_session_id"] is None
    assert payload["source_message_id"] is None
    assert payload["source_channel"] == "telegram"
    assert payload["goal"] == "Summarize a user message"
    assert payload["idempotency_key"] == "telegram:already-pseudonymous"


def test_content_fingerprint_is_deterministic_without_retaining_content() -> None:
    summary = "Nguyễn Văn A phone 0900000000 completed"

    fingerprint = content_fingerprint(summary)

    assert fingerprint["sha256"] == content_fingerprint(summary)["sha256"]
    assert re.fullmatch(r"[0-9a-f]{64}", fingerprint["sha256"])
    assert fingerprint["chars"] == len(summary)
    assert fingerprint["utf8_bytes"] == len(summary.encode("utf-8"))
    assert summary not in repr(fingerprint)


def test_workflow_resolver_uses_pseudonymous_telegram_idempotency() -> None:
    request = CoreRequest(
        text="Do the task",
        channel="telegram",
        source_chat_id="chat-secret",
        source_message_id="message-secret",
    )

    key = WorkflowResolver._idempotency_key(request)

    assert key == telegram_idempotency_key(
        source_chat_id="chat-secret",
        source_message_id="message-secret",
    )
    assert "chat-secret" not in key
    assert "message-secret" not in key


def test_openclaw_execution_contract_has_no_telegram_routing_identifiers() -> None:
    request = OpenClawExecutionRequest(
        task_id="task_1",
        run_id="run_1",
        attempt=1,
        idempotency_key="run_1:1",
        project_id="proj_1",
        goal="Process the requested work",
        mode="build",
    )

    payload = request.model_dump(mode="json")

    assert "source_chat_id" not in payload
    assert "source_session_id" not in payload
    assert "source_message_id" not in payload


def test_async_identity_fingerprint_is_versioned_and_keyed() -> None:
    from app.privacy import minimization as privacy

    payload = {"goal": "replace subject", "reference_image": None, "correlation_id": "a"}
    first = privacy.async_request_identity_fingerprint(payload, secret="server-secret-a")
    same = privacy.async_request_identity_fingerprint(
        payload | {"correlation_id": "b"}, secret="server-secret-a"
    )
    other_key = privacy.async_request_identity_fingerprint(payload, secret="server-secret-b")
    assert re.fullmatch(r"hmac-sha256-v1:primary-v1:[0-9a-f]{64}", first)
    assert first == same
    assert first != other_key


def test_async_identity_normalization_treats_missing_new_optional_field_as_default() -> None:
    from app.privacy import minimization as privacy

    legacy = {"goal": "same"}
    current = {"goal": "same", "reference_image": None}
    assert privacy.normalize_async_request_identity_payload(
        legacy
    ) == privacy.normalize_async_request_identity_payload(current)


def test_async_identity_fingerprint_verifies_previous_rotation_key() -> None:
    from app.privacy import minimization as privacy

    payload = {"goal": "replace subject", "reference_image": None}
    old = privacy.async_request_identity_fingerprint(
        payload, secret="old-secret", key_id="2026-08"
    )
    assert privacy.verify_async_request_identity_fingerprint(
        payload, old, secrets={"2026-09": "new-secret", "2026-08": "old-secret"}
    )
    assert not privacy.verify_async_request_identity_fingerprint(
        payload, old, secrets={"2026-09": "new-secret"}
    )
