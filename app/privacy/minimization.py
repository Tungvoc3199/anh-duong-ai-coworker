from __future__ import annotations

import hashlib
from typing import Any


def telegram_idempotency_key(
    *,
    source_chat_id: str,
    source_message_id: str,
) -> str:
    """Return a stable key without embedding Telegram routing identifiers."""
    material = f"{source_chat_id}\0{source_message_id}".encode()
    return "telegram:" + hashlib.sha256(material).hexdigest()


def legacy_telegram_idempotency_key(
    *, source_chat_id: str, source_message_id: str,
) -> str:
    """Return the pre-PDPA Telegram key shape for replay lookup only."""
    candidate = f"telegram:{source_chat_id}:{source_message_id}"
    if len(candidate) <= 255:
        return candidate
    return "telegram:" + hashlib.sha256(candidate.encode("utf-8")).hexdigest()


def canonicalize_telegram_idempotency_key(
    *,
    provided_key: str,
    source_chat_id: str | None,
    source_message_id: str | None,
) -> str:
    """Return a stable pseudonymous key for any Telegram submission."""
    if source_chat_id and source_message_id:
        return telegram_idempotency_key(
            source_chat_id=source_chat_id,
            source_message_id=source_message_id,
        )
    suffix = provided_key.removeprefix("telegram:")
    if provided_key.startswith("telegram:") and len(suffix) == 64 and all(
        char in "0123456789abcdef" for char in suffix
    ):
        return provided_key
    return "telegram:" + hashlib.sha256(provided_key.encode("utf-8")).hexdigest()


def minimize_async_request_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Remove routing identifiers not required to resume async execution."""
    minimized = dict(payload)
    for field in (
        "source_chat_id",
        "source_session_id",
        "source_message_id",
    ):
        if field in minimized:
            minimized[field] = None
    return minimized


def content_fingerprint(value: str) -> dict[str, int | str]:
    """Return audit-safe integrity metadata without retaining the content."""
    encoded = value.encode("utf-8")
    return {
        "sha256": hashlib.sha256(encoded).hexdigest(),
        "chars": len(value),
        "utf8_bytes": len(encoded),
    }
