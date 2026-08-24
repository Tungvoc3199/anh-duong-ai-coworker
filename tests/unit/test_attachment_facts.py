from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.orchestration import AttachmentFact, CoreRequest


def test_core_request_defaults_to_no_attachments() -> None:
    request = CoreRequest(text="alo")

    assert request.attachments == ()


def test_attachment_fact_accepts_bounded_document_metadata() -> None:
    fact = AttachmentFact(
        index=0,
        kind="document",
        content_type=(
            "application/vnd.openxmlformats-officedocument."
            "wordprocessingml.document"
        ),
        filename="test.docx",
        local_ref="/tmp/openclaw/media/test.docx",
        provider_ref="media://telegram/abc",
        staged=True,
        source_message_id="42",
    )

    assert fact.kind == "document"
    assert fact.filename == "test.docx"
    assert fact.staged is True


def test_attachment_fact_rejects_unbounded_summary() -> None:
    with pytest.raises(ValidationError):
        AttachmentFact(
            index=0,
            kind="document",
            content_summary="x" * 8001,
        )


def test_attachment_fact_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        AttachmentFact(
            index=0,
            kind="document",
            binary_payload="not-allowed",
        )
