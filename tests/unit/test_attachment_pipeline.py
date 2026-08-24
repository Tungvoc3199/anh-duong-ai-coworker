from __future__ import annotations

import json

from app.context_builder import ContextSectionKind
from app.orchestration import AttachmentFact, CoreRequest
from app.routing import FastRoute
from tests.unit.test_core_request_pipeline_behavior import (
    RecordingAuditWriter,
    _pipeline,
)


def test_pipeline_routes_and_renders_attachment_facts_without_audit_leak() -> None:
    audit_writer = RecordingAuditWriter()
    prepared = _pipeline(audit_writer=audit_writer).prepare(
        CoreRequest(
            text="File đây nhé",
            request_id="req-attachment",
            channel="telegram",
            actor="telegram:test",
            attachments=(
                AttachmentFact(
                    index=0,
                    kind="document",
                    content_type=(
                        "application/vnd.openxmlformats-officedocument."
                        "wordprocessingml.document"
                    ),
                    filename="a.docx",
                    local_ref="/tmp/openclaw/a.docx",
                    staged=True,
                    source_message_id="42",
                ),
            ),
        )
    )

    assert prepared.route_decision.route is FastRoute.DIRECT
    assert prepared.route_decision.rule_id == "routing.direct.attachment_context"
    current = next(
        section
        for section in prepared.context.sections
        if section.kind is ContextSectionKind.CURRENT_REQUEST
    )
    assert "Attachments:" in current.content
    assert "kind=document" in current.content
    assert "filename=a.docx" in current.content
    assert "local_ref=/tmp/openclaw/a.docx" in current.content
    assert "attachment:0" in current.source_refs
    assert "attachment:0" in prepared.provenance.context_source_refs

    event = audit_writer.events[-1]
    assert event.payload["attachment_count"] == 1
    audit_json = json.dumps(event.payload, ensure_ascii=False)
    assert "a.docx" not in audit_json
    assert "/tmp/openclaw/a.docx" not in audit_json
