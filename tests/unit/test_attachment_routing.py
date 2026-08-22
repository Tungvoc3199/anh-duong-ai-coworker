from __future__ import annotations

from app.orchestration import AttachmentFact
from app.routing import FastRoute, FastRouter


def test_document_attachment_without_side_effect_routes_direct() -> None:
    decision = FastRouter().route(
        "File đây nhé",
        attachments=(
            AttachmentFact(
                index=0,
                kind="document",
                filename="a.docx",
                staged=True,
            ),
        ),
    )

    assert decision.route is FastRoute.DIRECT
    assert decision.rule_id == "routing.direct.attachment_context"


def test_send_attachment_remains_workflow() -> None:
    decision = FastRouter().route(
        "Gửi file này cho Hải",
        attachments=(
            AttachmentFact(
                index=0,
                kind="document",
                filename="a.docx",
                staged=True,
            ),
        ),
    )

    assert decision.route is FastRoute.WORKFLOW
    assert decision.rule_id == "routing.workflow.explicit_action"
