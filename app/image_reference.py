from __future__ import annotations

import re
from pathlib import PurePosixPath
from urllib.parse import quote, unquote, urlsplit

_ALLOWED_IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp", ".gif"})
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}", re.I)
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")

def validate_managed_image_reference(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized or _CONTROL.search(normalized):
        raise ValueError("reference_image must be a canonical managed media URI")
    parsed = urlsplit(normalized)
    if parsed.scheme != "media" or parsed.netloc != "inbound" or parsed.query or parsed.fragment:
        raise ValueError("reference_image must use media://inbound")
    encoded_id = parsed.path.removeprefix("/")
    try:
        media_id = unquote(encoded_id, errors="strict")
    except (UnicodeDecodeError, ValueError) as error:
        raise ValueError("reference_image contains an invalid media id") from error
    if not media_id or "/" in media_id or "\\" in media_id or media_id in {".", ".."}:
        raise ValueError("reference_image must name one inbound media id")
    if quote(media_id, safe="-._~") != encoded_id:
        raise ValueError("reference_image must be canonically encoded")
    suffix = PurePosixPath(media_id).suffix.lower()
    if not _UUID.search(media_id) or suffix not in _ALLOWED_IMAGE_SUFFIXES:
        raise ValueError("reference_image must be a UUID-backed supported image")
    return normalized
