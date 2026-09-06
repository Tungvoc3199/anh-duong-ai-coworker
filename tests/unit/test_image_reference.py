from __future__ import annotations

import pytest

from app.image_reference import validate_managed_image_reference

VALID = "media://inbound/reply---11111111-1111-4111-8111-111111111111.jpg"

def test_reference_accepts_only_opaque_inbound_media_uri() -> None:
    assert validate_managed_image_reference(VALID) == VALID
    with pytest.raises(ValueError):
        validate_managed_image_reference("/home/node/.openclaw/media/inbound/reply.jpg")

@pytest.mark.parametrize("value", [
    "media://inbound/not-uuid.jpg",
    "media://inbound/a/b.jpg",
    "media://inbound/reply---11111111-1111-4111-8111-111111111111.jpg?x=1",
    "media://other/reply---11111111-1111-4111-8111-111111111111.jpg",
    "media://inbound/reply---11111111-1111-4111-8111-111111111111.jpg\x00",
])
def test_reference_rejects_noncanonical_or_untrusted_uri(value: str) -> None:
    with pytest.raises(ValueError):
        validate_managed_image_reference(value)


def test_reference_rejects_uuid_substring_without_producer_separator() -> None:
    value = "media://inbound/evil-11111111-1111-4111-8111-111111111111.jpg"
    with pytest.raises(ValueError):
        validate_managed_image_reference(value)

def test_reference_accepts_bare_openclaw_uuid_v4_id() -> None:
    value = "media://inbound/11111111-1111-4111-8111-111111111111.png"
    assert validate_managed_image_reference(value) == value
