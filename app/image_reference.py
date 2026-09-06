from __future__ import annotations

import re
from pathlib import PurePosixPath
from urllib.parse import quote, unquote, urlsplit

_ALLOWED_IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp", ".gif"})
_UUID_V4 = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}", re.I)
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
    stem = media_id[: -len(suffix)] if suffix else media_id
    producer_name = None
    uuid_text = stem
    if "---" in stem:
        producer_name, uuid_text = stem.rsplit("---", 1)
    valid_name = producer_name is None or (
        bool(producer_name)
        and all(char.isalnum() or char in "._-" for char in producer_name)
    )
    if (
        suffix not in _ALLOWED_IMAGE_SUFFIXES
        or not valid_name
        or _UUID_V4.fullmatch(uuid_text) is None
    ):
        raise ValueError("reference_image must match OpenClaw managed media ID grammar")
    return normalized
