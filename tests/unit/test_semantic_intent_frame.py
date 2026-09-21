from app.capabilities.models import CapabilityKind
from app.routing.models import FastRoute
from app.semantic_intent import (
    IntentAction,
    IntentAuthorization,
    IntentDomain,
    IntentSpeechAct,
    IntentTarget,
    SemanticIntentFrame,
    decisions_from_intent_frame,
)
from app.visual_interaction import VisualImageSource


def _frame(**updates):
    base = dict(
        speech_act=IntentSpeechAct.ASK,
        domain=IntentDomain.VISUAL,
        action=IntentAction.DISCUSS_EDIT,
        requested_execution=False,
        authorization=IntentAuthorization.NONE,
        recipient=None,
        channel=None,
        uses_contextual_visual=False,
        confidence=0.98,
    )
    base.update(updates)
    return SemanticIntentFrame(**base)


def test_advice_about_previously_sent_image_is_read_only() -> None:
    frame = _frame()
    route, capability, visual = decisions_from_intent_frame(
        frame,
        raw_instruction=(
            "Ok. Vậy với ý kiến của e như trên thì e tính sửa chi tiết nào "
            "ảnh a gửi cho sang choảnh hơn k"
        ),
        image_source=VisualImageSource.RECENT_ARTIFACT,
        reference_image="media://inbound/11111111-1111-4111-8111-111111111111.jpg",
    )
    assert route.route is FastRoute.DIRECT
    assert capability.capability is CapabilityKind.VISUAL_ANALYSIS
    assert visual is not None
    assert visual.operation.value == "analyze"
    assert visual.side_effect.value == "none"


def test_explicit_send_to_named_recipient_is_external_workflow() -> None:
    frame = _frame(
        speech_act=IntentSpeechAct.ACTION_REQUEST,
        domain=IntentDomain.EXTERNAL_COMMUNICATION,
        action=IntentAction.SEND,
        requested_execution=True,
        authorization=IntentAuthorization.EXPLICIT,
        recipient="Sang",
    )
    route, capability, visual = decisions_from_intent_frame(
        frame,
        raw_instruction="Gửi ảnh này cho Sang",
        image_source=VisualImageSource.REPLIED_IMAGE,
        reference_image="media://inbound/11111111-1111-4111-8111-111111111111.jpg",
    )
    assert route.route is FastRoute.WORKFLOW
    assert capability.capability is CapabilityKind.EXTERNAL_COMMUNICATION
    assert visual is not None
    assert visual.operation.value == "external_action"
    assert visual.side_effect.value == "send"


def test_question_about_sending_does_not_authorize_send() -> None:
    frame = _frame(
        speech_act=IntentSpeechAct.ASK,
        domain=IntentDomain.EXTERNAL_COMMUNICATION,
        action=IntentAction.SEND,
        requested_execution=False,
        authorization=IntentAuthorization.NONE,
        recipient="khách",
    )
    route, capability, visual = decisions_from_intent_frame(
        frame,
        raw_instruction="Em định gửi ảnh cho khách à?",
        image_source=VisualImageSource.REPLIED_IMAGE,
        reference_image="media://inbound/11111111-1111-4111-8111-111111111111.jpg",
    )
    assert route.route is FastRoute.DIRECT
    assert capability.capability is CapabilityKind.CONVERSATIONAL_RESPONSE
    assert visual is not None
    assert visual.side_effect.value == "none"


def test_prohibition_cannot_become_external_action() -> None:
    frame = _frame(
        speech_act=IntentSpeechAct.PROHIBITION,
        domain=IntentDomain.EXTERNAL_COMMUNICATION,
        action=IntentAction.SEND,
        requested_execution=False,
        authorization=IntentAuthorization.PROHIBITED,
        recipient="ai",
    )
    route, capability, visual = decisions_from_intent_frame(
        frame,
        raw_instruction="Đừng gửi ảnh cho ai",
        image_source=VisualImageSource.REPLIED_IMAGE,
        reference_image="media://inbound/11111111-1111-4111-8111-111111111111.jpg",
    )
    assert route.route is FastRoute.DIRECT
    assert capability.capability is CapabilityKind.CONVERSATIONAL_RESPONSE
    assert visual is not None
    assert visual.side_effect.value == "none"


def test_explicit_core_restart_maps_to_system_operation() -> None:
    frame = _frame(
        speech_act=IntentSpeechAct.ACTION_REQUEST,
        domain=IntentDomain.CORE,
        action=IntentAction.EXECUTE,
        target=IntentTarget.CORE,
        requested_execution=True,
        authorization=IntentAuthorization.EXPLICIT,
    )

    route, capability, visual = decisions_from_intent_frame(
        frame,
        raw_instruction="Khởi động lại dịch vụ Ánh Dương Core cho a.",
    )

    assert route.route is FastRoute.WORKFLOW
    assert capability.capability is CapabilityKind.SYSTEM_OPERATION
    assert visual is None


def test_read_only_analysis_cannot_be_promoted_to_workflow_execution() -> None:
    import pytest

    with pytest.raises(ValueError, match="read-only intent cannot request"):
        SemanticIntentFrame(
            speech_act=IntentSpeechAct.ACTION_REQUEST,
            domain=IntentDomain.VISUAL,
            action=IntentAction.ANALYZE,
            target="image",
            requested_execution=True,
            authorization=IntentAuthorization.EXPLICIT,
            confidence=0.99,
        )


def test_contextual_visual_flag_is_explicit_semantic_data() -> None:
    frame = _frame(uses_contextual_visual=True)
    assert frame.uses_contextual_visual is True
