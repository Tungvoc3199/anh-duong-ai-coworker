from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

REDACTED = "[REDACTED]"

_SENSITIVE_KEY_PATTERN = re.compile(
    r"""
    (^|[_-])
    (
        api[_-]?key
        |access[_-]?token
        |auth[_-]?token
        |authorization
        |bearer
        |bot[_-]?token
        |client[_-]?secret
        |credential
        |gateway[_-]?token
        |openclaw[_-]?gateway[_-]?token
        |password
        |passwd
        |private[_-]?key
        |refresh[_-]?token
        |secret
        |session[_-]?token
    )
    ($|[_-])
    """,
    flags=re.IGNORECASE | re.VERBOSE,
)

_BEARER_PATTERN = re.compile(
    r"\b(Bearer\s+)([A-Za-z0-9._~+/=-]+)",
    flags=re.IGNORECASE,
)

_ASSIGNMENT_PATTERN = re.compile(
    r"""
    \b(
        api[_-]?key
        |access[_-]?token
        |auth[_-]?token
        |bot[_-]?token
        |client[_-]?secret
        |gateway[_-]?token
        |openai[_-]?api[_-]?key
        |openclaw[_-]?gateway[_-]?token
        |password
        |passwd
        |private[_-]?key
        |refresh[_-]?token
        |secret
        |session[_-]?token
        |telegram[_-]?bot[_-]?token
    )
    (\s*[:=]\s*)
    (?:
        "[^"]+"
        |'[^']+'
        |[^\s&,;]+
    )
    """,
    flags=re.IGNORECASE | re.VERBOSE,
)

_QUERY_SECRET_PATTERN = re.compile(
    r"""
    ([?&])
    (
        api[_-]?key
        |access[_-]?token
        |auth[_-]?token
        |client[_-]?secret
        |password
        |refresh[_-]?token
        |secret
        |session[_-]?token
        |token
    )
    (=)
    ([^&#\s]+)
    """,
    flags=re.IGNORECASE | re.VERBOSE,
)

_PROVIDER_KEY_PATTERNS = (
    re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{10,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
    re.compile(r"\b\d{6,}:[A-Za-z0-9_-]{20,}\b"),
)


class SecretRedactor:
    """Recursively redact known secret keys and token shapes."""

    def redact(self, value: Any) -> Any:
        if isinstance(value, str):
            return self._redact_text(value)

        if isinstance(value, Mapping):
            return {
                key: (
                    REDACTED
                    if self._is_sensitive_key(str(key))
                    else self.redact(item)
                )
                for key, item in value.items()
            }

        if isinstance(value, tuple):
            return tuple(self.redact(item) for item in value)

        if isinstance(value, Sequence) and not isinstance(
            value,
            (str, bytes, bytearray),
        ):
            return [self.redact(item) for item in value]

        return value

    @staticmethod
    def _is_sensitive_key(key: str) -> bool:
        return _SENSITIVE_KEY_PATTERN.search(
            key.strip().lower()
        ) is not None

    def _redact_text(self, text: str) -> str:
        if text == REDACTED:
            return text

        stripped = text.strip()
        if any(
            pattern.fullmatch(stripped)
            for pattern in _PROVIDER_KEY_PATTERNS
        ):
            return REDACTED

        result = _BEARER_PATTERN.sub(
            lambda match: f"{match.group(1)}{REDACTED}",
            text,
        )

        result = _ASSIGNMENT_PATTERN.sub(
            lambda match: (
                f"{match.group(1)}"
                f"{match.group(2)}"
                f"{REDACTED}"
            ),
            result,
        )

        result = _QUERY_SECRET_PATTERN.sub(
            lambda match: (
                f"{match.group(1)}"
                f"{match.group(2)}"
                f"{match.group(3)}"
                f"{REDACTED}"
            ),
            result,
        )

        for pattern in _PROVIDER_KEY_PATTERNS:
            result = pattern.sub(REDACTED, result)

        return result
