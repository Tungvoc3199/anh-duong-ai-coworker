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


def async_request_identity_fingerprint(
    payload: dict[str, Any], *, secret: str, key_id: str = "primary-v1"
) -> str:
    """Return a versioned keyed fingerprint of semantic async request identity."""
    identity = normalize_async_request_identity_payload(payload)
    canonical = json.dumps(identity, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    material = b"anh-duong:async-request-identity:v1\0" + canonical.encode("utf-8")
    digest = hmac.new(secret.encode("utf-8"), material, hashlib.sha256).hexdigest()
    if not key_id or ":" in key_id:
        raise ValueError("async identity HMAC key_id is invalid")
    return f"hmac-sha256-v1:{key_id}:{digest}"


def verify_async_request_identity_fingerprint(
    payload: dict[str, Any], fingerprint: str, *, secrets: dict[str, str]
) -> bool:
    parts = fingerprint.split(":")
    if len(parts) == 3 and parts[0] == "hmac-sha256-v1":
        key_id = parts[1]
        secret = secrets.get(key_id)
        if secret is None:
            return False
        expected = async_request_identity_fingerprint(payload, secret=secret, key_id=key_id)
        return hmac.compare_digest(fingerprint, expected)
    if len(parts) == 2 and parts[0] == "hmac-sha256-v1":
        # Compatibility for pre-key-id candidate rows: try every retained key.
        return any(
            hmac.compare_digest(
                fingerprint,
                "hmac-sha256-v1:" + async_request_identity_fingerprint(
                    payload, secret=secret, key_id=key_id
                ).rsplit(":", 1)[1],
            )
            for key_id, secret in secrets.items()
        )
    return False


def legacy_async_request_identity_sha256(payload: dict[str, Any]) -> str:
    """Return the pre-HMAC fingerprint only for compatibility with existing rows."""
    identity = normalize_async_request_identity_payload(payload)
    canonical = json.dumps(identity, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def resolve_async_identity_hmac_keyring() -> tuple[str, dict[str, str]]:
    """Resolve active and retained server-side identity HMAC keys."""
    from app.config import get_settings

    settings = get_settings()
    active_id = settings.async_identity_hmac_key_id
    active_secret = settings.async_identity_hmac_secret or settings.approval_hmac_secret
    if not active_id or ":" in active_id or not active_secret:
        raise RuntimeError("async identity HMAC keyring is invalid")
    keys = dict(settings.async_identity_hmac_previous_keys)
    keys[active_id] = active_secret
    if any((not key_id or ":" in key_id or not secret) for key_id, secret in keys.items()):
        raise RuntimeError("async identity HMAC keyring is invalid")
    return active_id, keys


def resolve_async_identity_hmac_secret() -> str:
    """Compatibility accessor for the active server-side identity key."""
    active_id, keys = resolve_async_identity_hmac_keyring()
    return keys[active_id]


def content_fingerprint(value: str) -> dict[str, int | str]:
    """Return audit-safe integrity metadata without retaining the content."""
    encoded = value.encode("utf-8")
    return {
        "sha256": hashlib.sha256(encoded).hexdigest(),
        "chars": len(value),
        "utf8_bytes": len(encoded),
    }
