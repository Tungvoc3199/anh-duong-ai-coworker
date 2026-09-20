import json

import httpx
import pytest

from app.orchestration.models import ContextualReferent
from app.semantic_intent import IntentAction, IntentDomain, IntentSpeechAct
from app.semantic_intent_resolver import (
    OpenClawSemanticIntentResolver,
    SemanticIntentResolutionError,
)
from app.visual_interaction import VisualImageSource


def _response(payload: dict[str, object]) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "id": "resp_semantic",
            "output": [
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": json.dumps(payload, ensure_ascii=False),
                        }
                    ],
                }
            ],
        },
    )


def test_resolver_is_tool_free_and_keeps_context_as_reference_data() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content.decode()))
        return _response(
            {
                "speech_act": "ask",
                "domain": "visual",
                "action": "discuss_edit",
                "target": "image",
                "requested_execution": False,
                "authorization": "none",
                "recipient": None,
                "channel": None,
                "uses_contextual_visual": True,
                "confidence": 0.99,
                "rationale": "Asks what should be edited to make the image more elegant.",
            }
        )

    resolver = OpenClawSemanticIntentResolver(
        base_url="http://openclaw.test",
        auth_token="secret",
        transport=httpx.MockTransport(handler),
    )
    referent = ContextualReferent(
        source="quoted_message",
        message_id="6003",
        text="Earlier discussion about preserving the original pose.",
        sender="Ánh Dương",
    )

    frame = resolver.resolve(
        current_text=(
            "Ok. Vậy với ý kiến của e như trên thì e tính sửa chi tiết nào "
            "ảnh a gửi cho sang choảnh hơn k"
        ),
        contextual_referent=referent,
        image_source=VisualImageSource.RECENT_ARTIFACT,
        has_reference_image=True,
        has_recent_image_candidate=True,
    )

    assert seen["tools"] == []
    assert seen["tool_choice"] == "none"
    assert seen["max_output_tokens"] == 700
    assert seen["reasoning"] == {"effort": "low"}
    semantic_input = json.loads(str(seen["input"]))
    assert semantic_input["current_user_turn"].endswith("cho sang choảnh hơn k")
    assert semantic_input["contextual_reference_data"]["message_id"] == "6003"
    assert frame.speech_act is IntentSpeechAct.ASK
    assert frame.domain is IntentDomain.VISUAL
    assert frame.action is IntentAction.DISCUSS_EDIT
    assert frame.requested_execution is False
    assert frame.uses_contextual_visual is True


def test_resolver_rejects_invalid_execution_authority() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return _response(
            {
                "speech_act": "ask",
                "domain": "external_communication",
                "action": "send",
                "target": "external_recipient",
                "requested_execution": True,
                "authorization": "none",
                "recipient": "Sang",
                "channel": None,
                "confidence": 0.9,
            }
        )

    resolver = OpenClawSemanticIntentResolver(
        base_url="http://openclaw.test",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(SemanticIntentResolutionError):
        resolver.resolve(
            current_text="Em định gửi ảnh cho Sang à?",
            contextual_referent=None,
            image_source=VisualImageSource.REPLIED_IMAGE,
            has_reference_image=True,
            has_recent_image_candidate=False,
        )


def test_resolver_http_failure_is_fail_safe() -> None:
    resolver = OpenClawSemanticIntentResolver(
        base_url="http://openclaw.test",
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(503, json={"error": "unavailable"})
        ),
    )

    with pytest.raises(SemanticIntentResolutionError):
        resolver.resolve(
            current_text="Gửi ảnh này cho Sang",
            contextual_referent=None,
            image_source=VisualImageSource.REPLIED_IMAGE,
            has_reference_image=True,
            has_recent_image_candidate=False,
        )
