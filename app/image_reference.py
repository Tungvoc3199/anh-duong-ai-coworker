from __future__ import annotations

from pathlib import PurePosixPath

_ALLOWED_IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp", ".gif"})
_MANAGED_MEDIA_PREFIX = ("/", "home", "node", ".openclaw", "media")


def validate_managed_image_reference(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        raise ValueError("reference_image cannot be blank")
    path = PurePosixPath(normalized)
    if path.parts[:5] != _MANAGED_MEDIA_PREFIX or ".." in path.parts:
        raise ValueError("reference_image must be inside managed OpenClaw media")
    if path.suffix.lower() not in _ALLOWED_IMAGE_SUFFIXES:
        raise ValueError("reference_image must be a supported image")
    return normalized
