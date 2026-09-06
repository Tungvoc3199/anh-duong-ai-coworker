from __future__ import annotations

import hashlib
import hmac
import json
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


def normalize_async_request_identity_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Return version-stable semantic identity with transport metadata removed."""
    identity = minimize_async_request_payload(payload)
    identity.pop("idempotency_key", None)
    identity.pop("correlation_id", None)
    identity.pop("_semantic_identity_sha256", None)
    identity.pop("_semantic_identity_fingerprint", None)
    identity.setdefault("reference_image", None)
    return identity


def async_request_identity_fingerprint(payload: dict[str, Any], *, secret: str) -> str:
    """Return a versioned keyed fingerprint of semantic async request identity."""
    identity = normalize_async_request_identity_payload(payload)
    canonical = json.dumps(identity, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    material = b"anh-duong:async-request-identity:v1\0" + canonical.encode("utf-8")
    digest = hmac.new(secret.encode("utf-8"), material, hashlib.sha256).hexdigest()
    return f"hmac-sha256-v1:{digest}"


def legacy_async_request_identity_sha256(payload: dict[str, Any]) -> str:
    """Return the pre-HMAC fingerprint only for compatibility with existing rows."""
    identity = normalize_async_request_identity_payload(payload)
    canonical = json.dumps(identity, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def resolve_async_identity_hmac_secret() -> str:
    """Resolve the server-side identity key with backward-compatible config fallback."""
    from app.config import get_settings

    settings = get_settings()
    secret = settings.async_identity_hmac_secret or settings.approval_hmac_secret
    if not secret:
        raise RuntimeError("async identity HMAC secret is required")
    return secret


def content_fingerprint(value: str) -> dict[str, int | str]:
    """Return audit-safe integrity metadata without retaining the content."""
    encoded = value.encode("utf-8")
    return {
        "sha256": hashlib.sha256(encoded).hexdigest(),
        "chars": len(value),
        "utf8_bytes": len(encoded),
    }
