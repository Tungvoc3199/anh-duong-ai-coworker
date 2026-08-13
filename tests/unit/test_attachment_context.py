from __future__ import annotations

from app.context_builder import ContextBuilder, ContextSectionKind
from tests.unit.test_context_builder import RecordingRetriever, _build_request


def test_attachment_context_is_rendered_with_current_request() -> None:
    request = _build_request().model_copy(
        update={
            "attachment_context": (
                "index=0 kind=document filename=a.docx "
                "content_type=application/vnd.openxmlformats-officedocument."
                "wordprocessingml.document staged=true",
            )
        }
    )

    bundle = ContextBuilder(RecordingRetriever([])).build(request)

    current = next(
        section
        for section in bundle.sections
        if section.kind is ContextSectionKind.CURRENT_REQUEST
    )
    assert "Triển khai Context Builder v1" in current.content
    assert "Attachments:" in current.content
    assert "filename=a.docx" in current.content
    assert "attachment:0" in current.source_refs
