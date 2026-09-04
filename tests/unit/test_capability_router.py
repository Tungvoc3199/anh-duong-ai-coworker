import pytest
from pydantic import ValidationError

from app.capabilities import (
    CapabilityDecision,
    CapabilityKind,
    CapabilityRouter,
)
from app.routing import FastRoute, FastRouter, RouteDecision


def _route(request: str) -> CapabilityDecision:
    fast_decision = FastRouter().route(request)
    return CapabilityRouter().route(fast_decision, request)


def test_capability_kind_contains_exact_v1_contract() -> None:
    assert {kind.value for kind in CapabilityKind} == {
        "conversational_response",
        "memory_search",
        "project_read",
        "task_read",
        "core_status_read",
        "planning",
        "visual_prompt_compose",
        "visual_image_generate",
        "file_operation",
        "code_operation",
        "external_communication",
        "system_operation",
        "unknown_workflow",
    }


@pytest.mark.parametrize(
    ("text", "expected_capability", "expected_route"),
    [
        (
            "Xin chào!",
            CapabilityKind.CONVERSATIONAL_RESPONSE,
            FastRoute.DIRECT,
        ),
        (
            "Bạn có nhớ tôi đã nói gì về ngân sách không?",
            CapabilityKind.MEMORY_SEARCH,
            FastRoute.MEMORY,
        ),
        (
            "Tiến độ Project Atlas thế nào?",
            CapabilityKind.PROJECT_READ,
            FastRoute.CORE_READ,
        ),
        (
            "Task FR-1 đang ở trạng thái nào?",
            CapabilityKind.TASK_READ,
            FastRoute.CORE_READ,
        ),
        (
            "Kiểm tra health của Ánh Dương Core.",
            CapabilityKind.CORE_STATUS_READ,
            FastRoute.CORE_READ,
        ),
        (
            "Hãy lập kế hoạch cho CR-1.",
            CapabilityKind.PLANNING,
            FastRoute.WORKFLOW,
        ),
        (
            "Tạo file báo cáo.md.",
            CapabilityKind.FILE_OPERATION,
            FastRoute.WORKFLOW,
        ),
        (
            "Chạy pytest cho app.",
            CapabilityKind.CODE_OPERATION,
            FastRoute.WORKFLOW,
        ),
        (
            "Gửi báo cáo qua email.",
            CapabilityKind.EXTERNAL_COMMUNICATION,
            FastRoute.WORKFLOW,
        ),
        (
            "Khởi động lại service Core.",
            CapabilityKind.SYSTEM_OPERATION,
            FastRoute.WORKFLOW,
        ),
        (
            "Phân tích việc này.",
            CapabilityKind.CONVERSATIONAL_RESPONSE,
            FastRoute.DIRECT,
        ),
    ],
)
def test_routes_all_v1_capabilities(
    text: str,
    expected_capability: CapabilityKind,
    expected_route: FastRoute,
) -> None:
    decision = _route(text)

    assert decision.capability is expected_capability
    assert decision.source_route is expected_route
    assert decision.reason_code
    if expected_capability is not CapabilityKind.UNKNOWN_WORKFLOW:
        assert decision.matched_signals


@pytest.mark.parametrize(
    ("text", "expected_capability"),
    [
        (
            "Trạng thái Task FR-1 của Project Atlas thế nào?",
            CapabilityKind.TASK_READ,
        ),
        (
            "Trạng thái Project Atlas trên Ánh Dương Core thế nào?",
            CapabilityKind.PROJECT_READ,
        ),
    ],
)
def test_core_read_uses_entity_specificity_precedence(
    text: str,
    expected_capability: CapabilityKind,
) -> None:
    assert _route(text).capability is expected_capability


@pytest.mark.parametrize(
    ("text", "expected_capability"),
    [
        (
            "Lập kế hoạch khởi động lại service rồi gửi email.",
            CapabilityKind.SYSTEM_OPERATION,
        ),
        (
            "Chạy pytest rồi gửi kết quả qua Slack.",
            CapabilityKind.EXTERNAL_COMMUNICATION,
        ),
        (
            "Lập kế hoạch sửa code và chạy pytest.",
            CapabilityKind.CODE_OPERATION,
        ),
        (
            "Lập kế hoạch tạo file báo cáo.md.",
            CapabilityKind.FILE_OPERATION,
        ),
    ],
)
def test_workflow_precedence_protects_side_effects(
    text: str,
    expected_capability: CapabilityKind,
) -> None:
    assert _route(text).capability is expected_capability


@pytest.mark.parametrize(
    ("text", "expected_capability"),
    [
        ("Deploy the API service.", CapabilityKind.SYSTEM_OPERATION),
        ("Publish the report externally.", CapabilityKind.EXTERNAL_COMMUNICATION),
        ("Generate a Python module.", CapabilityKind.CODE_OPERATION),
        ("List files in the reports folder.", CapabilityKind.FILE_OPERATION),
        ("Break down Task CR-1 into steps.", CapabilityKind.PLANNING),
        ("Call the deployment webhook.", CapabilityKind.EXTERNAL_COMMUNICATION),
    ],
)
def test_workflow_contract_action_variants(
    text: str,
    expected_capability: CapabilityKind,
) -> None:
    assert _route(text).capability is expected_capability

def test_empty_input_fails_closed() -> None:
    decision = _route(" \n\t ")

    assert decision == CapabilityDecision(
        capability=CapabilityKind.UNKNOWN_WORKFLOW,
        source_route=FastRoute.WORKFLOW,
        reason_code="capability.workflow.empty_input",
        matched_signals=(),
    )


@pytest.mark.parametrize(
    "route_decision",
    [
        RouteDecision(
            route=FastRoute.DIRECT,
            rule_id="routing.direct.simple_conversation",
            reason="The request is a simple conversational response.",
        ),
        RouteDecision(
            route=FastRoute.WORKFLOW,
            rule_id="forged.rule",
            reason="Forged upstream decision.",
        ),
    ],
)
def test_inconsistent_fast_router_decision_fails_closed(
    route_decision: RouteDecision,
) -> None:
    decision = CapabilityRouter().route(route_decision, "Tạo file report.md.")

    assert decision.capability is CapabilityKind.UNKNOWN_WORKFLOW
    assert decision.source_route is route_decision.route
    assert decision.reason_code == "capability.workflow.inconsistent_route"
    assert decision.matched_signals == ()


def test_capability_decision_is_immutable() -> None:
    decision = _route("Xin chào!")

    with pytest.raises(ValidationError):
        decision.capability = CapabilityKind.UNKNOWN_WORKFLOW


def test_capability_package_exports_public_contract() -> None:
    from app.capabilities import CapabilityDecision as ExportedDecision
    from app.capabilities import CapabilityKind as ExportedKind
    from app.capabilities import CapabilityRouter as ExportedRouter

    assert ExportedDecision is CapabilityDecision
    assert ExportedKind is CapabilityKind
    assert ExportedRouter is CapabilityRouter


@pytest.mark.parametrize(
    "text",
    [
        "Tạo ảnh TikTok bán serum dưỡng sáng, tỷ lệ 9:16.",
        "Làm hình quảng cáo serum cho anh.",
        "Generate an image for a product post.",
    ],
)
def test_explicit_image_requests_route_visual_image_generation(text: str) -> None:
    decision = _route(text)

    assert decision.capability.value == "visual_image_generate"
    assert decision.source_route is FastRoute.WORKFLOW
    assert decision.reason_code == "capability.workflow.visual_image_generate"


def test_prompt_request_does_not_upgrade_to_image_generation() -> None:
    decision = _route("Tạo prompt ảnh poster khai trương.")

    assert decision.capability is CapabilityKind.VISUAL_PROMPT_COMPOSE


def test_quoted_restart_text_does_not_upgrade_image_to_system_operation() -> None:
    decision = _route('Tạo ảnh poster, text chính xác "RESTART SERVICE NOW".')

    assert decision.capability.value == "visual_image_generate"


def test_publish_after_image_stays_external_communication() -> None:
    decision = _route("Tạo ảnh rồi đăng Facebook cho anh.")

    assert decision.capability is CapabilityKind.EXTERNAL_COMMUNICATION


@pytest.mark.parametrize(
    "text",
    [
        "E làm luôn 1 ảnh minh hoạ chủ đề ChatGPT bị gián đoạn toàn cầu "
        "để đăng Facebook theo phương án mình vừa bàn nhé.",
        "Tạo ảnh quảng cáo để đăng Facebook.",
        "Generate an image to post on Facebook.",
        "Generate an image for a Facebook post.",
        "Please create an image for a Facebook post.",
        "Generate an image to post on social media.",
        "Generate an image for a social media post.",
    ],
)
def test_social_destination_as_image_purpose_stays_image(text: str) -> None:
    decision = _route(text)
    assert decision.capability is CapabilityKind.VISUAL_IMAGE_GENERATE


@pytest.mark.parametrize(
    "text",
    [
        "Tạo ảnh rồi đăng Facebook cho anh.",
        "Generate an image; post it on Facebook.",
        "Generate an image to post on Facebook now.",
        "Generate an image for a Facebook post and email it to Alice.",
    ],
)
def test_explicit_external_action_after_image_remains_governed(text: str) -> None:
    decision = _route(text)
    assert decision.capability is CapabilityKind.EXTERNAL_COMMUNICATION


@pytest.mark.parametrize(
    "text",
    [
        "Then generate an image to post on Facebook.",
    ],
)
def test_benign_discourse_before_image_goal_stays_image(text: str) -> None:
    assert _route(text).capability is CapabilityKind.VISUAL_IMAGE_GENERATE


@pytest.mark.parametrize(
    "text",
    [
        "Generate an image to post on Facebook, now.",
        'Generate an image for a Facebook post "and email it to Alice".',
    ],
)
def test_immediate_or_quoted_external_tail_remains_governed(text: str) -> None:
    assert _route(text).capability is CapabilityKind.EXTERNAL_COMMUNICATION


@pytest.mark.parametrize(
    "text",
    [
        "Generate an image to post on Facebook right now.",
        "Generate an image to post on Facebook ASAP.",
        "Generate an image to post on Facebook at 5 PM.",
        "Tạo ảnh để đăng Facebook bây giờ.",
    ],
)
def test_timed_social_execution_remains_external(text: str) -> None:
    assert _route(text).capability is CapabilityKind.EXTERNAL_COMMUNICATION


def test_separate_sentence_intended_use_stays_image() -> None:
    text = "Generate an image. It is for a Facebook post."
    assert _route(text).capability is CapabilityKind.VISUAL_IMAGE_GENERATE


@pytest.mark.parametrize(
    "text",
    [
        "Generate an image to post on Facebook, please do it now.",
        "Generate an image to post on Facebook -- now.",
        "Tạo ảnh để đăng Facebook nhé, làm ngay.",
    ],
)
def test_delayed_immediacy_after_social_purpose_remains_external(text: str) -> None:
    assert _route(text).capability is CapabilityKind.EXTERNAL_COMMUNICATION


@pytest.mark.parametrize(
    "text",
    [
        "Generate an image to post on Facebook tomorrow.",
        "Generate an image to post on Facebook tonight.",
        "Generate an image to post on Facebook at noon.",
        "Tạo ảnh để đăng Facebook ngày mai.",
        (
            "Generate an image for a Facebook post and "
            + ("keep the design minimal " * 8)
            + "then post it."
        ),
    ],
)
def test_scheduled_or_long_tail_external_action_remains_governed(text: str) -> None:
    assert _route(text).capability is CapabilityKind.EXTERNAL_COMMUNICATION


def test_accentless_vietnamese_image_purpose_stays_image() -> None:
    assert _route("Tao anh de dang Facebook.").capability is CapabilityKind.VISUAL_IMAGE_GENERATE


def test_long_cross_sentence_purpose_stays_image() -> None:
    text = (
        "Generate an image "
        + ("with detailed visual guidance " * 12)
        + ". It is for a Facebook post."
    )
    assert _route(text).capability is CapabilityKind.VISUAL_IMAGE_GENERATE


@pytest.mark.parametrize("text", [
    "Generate an image for you to post on Facebook.",
    "Create an image that I want you to post on Facebook.",
])
def test_agentive_social_posting_remains_external(text: str) -> None:
    assert _route(text).capability is CapabilityKind.EXTERNAL_COMMUNICATION


@pytest.mark.parametrize("text", [
    "Generate an image, then have Alice post on Facebook.",
    "Generate an image and ask Bob to post on Facebook.",
])
def test_third_party_posting_remains_external(text: str) -> None:
    assert _route(text).capability is CapabilityKind.EXTERNAL_COMMUNICATION
