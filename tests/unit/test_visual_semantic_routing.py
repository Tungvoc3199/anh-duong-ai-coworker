from datetime import UTC, datetime

import pytest

from app.capabilities import CapabilityKind, CapabilityRouter
from app.orchestration.models import CoreRequest
from app.orchestration.workflow import WorkflowResolver
from app.policy import DecisionKind, RiskLevel
from app.projects.models import Project, ProjectPriority, ProjectStatus
from app.routing import FastRoute, FastRouter


def _route(text: str):
    fast = FastRouter().route(text)
    return fast, CapabilityRouter().route(fast, text)


@pytest.mark.parametrize(
    "text",
    [
        "Tạo cho anh 1 ảnh váy đỏ để đăng Facebook, xong gửi lại đây.",
        "Làm giúp anh một hình 4:5 dùng cho bài Facebook, chỉ gửi đúng một hình.",
        "Tạo ảnh cho content FB rồi trả cho anh trong chat này.",
        "Cho anh ảnh sản phẩm để anh tự đăng Facebook, tạo xong gửi lại cho anh.",
        "Tạo một hình để up FB, đừng đăng hộ anh, chỉ trả ảnh thôi.",
        "Làm ảnh cho content TikTok. Xong gửi đúng 1 ảnh vào đây.",
        "Tạo poster dùng làm content Instagram rồi gửi lại đây.",
        "Tạo hình để share Facebook, anh tự đăng, em chỉ gửi ảnh.",
        "Tao anh de dang Facebook, tao xong gui lai day.",
        "Lam hinh cho content FB, chi gui dung 1 anh.",
        "Generate one image for my Facebook post and send it back here.",
        "Create a 4:5 image for Instagram content; return it in this chat.",
        "Make a product image to post on Facebook. Send one image back to me.",
        "Generate a visual for social media content; return exactly one image here.",
        "Create an image intended for a TikTok post. Return the result to me here.",
        "Ảnh này để đăng Facebook. Tạo giúp anh, xong trả kết quả ở đây.",
        "Tạo cho anh tấm hình để làm content Zalo, không đăng, chỉ gửi lại.",
        "Làm một ảnh quảng cáo Facebook, cho anh đúng một ảnh thôi.",
        "Tạo ảnh để chạy quảng cáo Facebook, xong gửi cho anh qua Telegram.",
        "Tạo ảnh bìa cho FB, trả ảnh về đây, không gửi cho ai khác.",
    ],
)
def test_natural_visual_requests_keep_image_goal_and_source_delivery(text: str) -> None:
    fast, decision = _route(text)
    assert fast.route is FastRoute.WORKFLOW
    assert decision.capability is CapabilityKind.VISUAL_IMAGE_GENERATE


@pytest.mark.parametrize(
    "text",
    [
        "Tạo ảnh rồi đăng nó lên Facebook cho anh.",
        "Tạo ảnh xong post thẳng lên FB hộ anh.",
        "Làm ảnh rồi share lên Facebook luôn.",
        "Tạo ảnh rồi up Instagram cho anh.",
        "Tạo ảnh xong gửi cho Tuấn qua Telegram.",
        "Làm hình rồi gửi kết quả sang Slack.",
        "Create an image, then email it to Alice.",
        "Generate an image and publish it to Instagram now.",
        "Make an image, then send it to Bob on Telegram.",
        "Generate an image and call the webhook with the result.",
        "Tạo ảnh rồi nhờ Nam đăng Facebook.",
        "Generate an image and ask Bob to post on Facebook.",
    ],
)
def test_natural_visual_requests_keep_real_external_effects_governed(text: str) -> None:
    _, decision = _route(text)
    assert decision.capability is CapabilityKind.EXTERNAL_COMMUNICATION


def test_exact_1451_request_builds_owner_allowed_image_workflow() -> None:
    goal = (
        "Tạo cho anh đúng 1 ảnh thời trang nữ cao cấp để đăng Facebook.\n"
        "Yêu cầu:\n"
        "Người mẫu nữ mặc váy đỏ burgundy hiện đại, thanh lịch\n"
        "Background studio màu be tối giản\n"
        "Ánh sáng editorial cao cấp, da và chất liệu váy chân thực\n"
        "Bố cục toàn thân, sang trọng\n"
        "Tỷ lệ dọc 4:5\n"
        "Không chữ, không logo, không watermark\n"
        "Chỉ tạo và gửi đúng 1 ảnh, không gửi trùng\n"
        "Tự thực hiện luôn, không hỏi lại."
    )
    fast, capability = _route(goal)
    assert fast.route is FastRoute.WORKFLOW
    assert capability.capability is CapabilityKind.VISUAL_IMAGE_GENERATE

    now = datetime.now(UTC)
    project = Project(
        id="proj_vf_semantic",
        name="VisualForge",
        slug="visualforge-semantic",
        status=ProjectStatus.ACTIVE,
        priority=ProjectPriority.HIGH,
        path_windows=None,
        path_wsl="/home/thadc/AIOS/anh-duong-core",
        repo_url=None,
        current_phase=None,
        owner="user",
        summary=None,
        next_action=None,
        constraints=(),
        created_at=now,
        updated_at=now,
        last_activity_at=None,
        version=1,
    )
    envelope = WorkflowResolver().resolve(
        request=CoreRequest(
            text=goal,
            channel="telegram",
            actor="telegram:test",
            project_id=project.id,
            source_chat_id="chat",
            source_session_id="session",
            source_message_id="message-1451-natural-image",
        ),
        request_id="req_1451_natural_image",
        normalized_text=goal,
        capability=capability.capability,
        project=project,
    )
    assert envelope.risk_level is RiskLevel.READ_ONLY
    assert envelope.approval_required is False
    assert envelope.policy_decision is DecisionKind.ALLOW
    assert "one_image_max" in envelope.constraints
    assert "retry_delivery_without_regeneration" in envelope.constraints


def test_quoted_copy_is_not_a_system_effect_but_real_restart_still_is() -> None:
    _, quoted = _route('Tạo ảnh poster với text "RESTART SERVICE NOW".')
    _, real = _route('Tạo ảnh với text "RESTART SERVICE NOW", rồi restart service Core.')
    assert quoted.capability is CapabilityKind.VISUAL_IMAGE_GENERATE
    assert real.capability is CapabilityKind.SYSTEM_OPERATION


@pytest.mark.parametrize(
    "text",
    [
        "Tạo ảnh, anh sẽ tự đăng Facebook, gửi lại đây cho anh.",
        "Tạo ảnh để khách hàng đăng Facebook, trả ảnh về đây.",
        "Create an image. I will post it on Facebook; send it back here.",
        "Tạo ảnh, không đăng Facebook, không gửi cho ai khác, chỉ trả ảnh cho anh.",
        "Create an image; don't post or send it anywhere, return it here.",
    ],
)
def test_owner_or_non_agent_social_action_is_purpose_not_bot_side_effect(text: str) -> None:
    _, decision = _route(text)
    assert decision.capability is CapabilityKind.VISUAL_IMAGE_GENERATE


@pytest.mark.parametrize(
    "text",
    [
        "Tạo ảnh, không đăng Facebook nhưng gửi cho Nam qua Telegram.",
        "Tạo ảnh, không gửi cho ai, nhưng đăng Facebook cho anh.",
        "Create an image; don't post it, but send it to Alice.",
    ],
)
def test_negated_effect_does_not_hide_later_positive_external_effect(text: str) -> None:
    _, decision = _route(text)
    assert decision.capability is CapabilityKind.EXTERNAL_COMMUNICATION
