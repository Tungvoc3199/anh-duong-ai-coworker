from datetime import UTC, datetime

from app.capabilities import CapabilityKind, CapabilityRouter
from app.orchestration.models import CoreRequest
from app.orchestration.workflow import WorkflowResolver
from app.policy import DecisionKind, PolicyAction, PolicyEngine, RiskLevel
from app.projects.models import Project, ProjectPriority, ProjectStatus
from app.routing import FastRoute, FastRouter


def _capability(goal: str):
    route = FastRouter().route(goal)
    return route, CapabilityRouter().route(route, goal)


def test_negative_safety_constraints_stay_visual() -> None:
    goal = (
        'Dùng VisualForge tạo prompt ảnh TikTok bán serum, text "GIẢM 50%". '
        "Không gọi model hoặc OpenClaw. Không sửa file, config hoặc service."
    )
    route, capability = _capability(goal)
    assert route.route is FastRoute.WORKFLOW
    assert capability.capability is CapabilityKind.VISUAL_PROMPT_COMPOSE


def test_positive_system_side_effect_stays_system_operation() -> None:
    route, capability = _capability("Tạo prompt ảnh sản phẩm rồi restart service")
    assert route.route is FastRoute.WORKFLOW
    assert capability.capability is CapabilityKind.SYSTEM_OPERATION


def test_quoted_copy_does_not_trigger_system_operation() -> None:
    route, capability = _capability(
        'Tạo prompt ảnh poster, text chính xác "RESTART SERVICE NOW"'
    )
    assert route.route is FastRoute.WORKFLOW
    assert capability.capability is CapabilityKind.VISUAL_PROMPT_COMPOSE


def test_exact_telegram_request_routes_visual() -> None:
    goal = (
        "Dùng VisualForge tạo prompt ảnh TikTok bán serum dưỡng sáng, tỷ lệ 9:16. "
        'Text hiển thị chính xác: "DƯỠNG SÁNG DA – GIẢM 50% HÔM NAY". '
        "Dùng VisualForge local. Không gọi model hoặc OpenClaw để soạn prompt. "
        "Không truy cập mạng trong bước VisualForge. Không sửa file, config hoặc service. "
        "Trả prompt đã compile và giữ nguyên chính xác text trên."
    )
    route, capability = _capability(goal)
    assert route.route is FastRoute.WORKFLOW
    assert capability.capability is CapabilityKind.VISUAL_PROMPT_COMPOSE


def test_policy_catalog_allows_read_only_compose() -> None:
    decision = PolicyEngine.with_default_roots().evaluate(
        PolicyAction(
            name="compose_visual_prompt",
            declared_risk_level=RiskLevel.READ_ONLY,
        )
    )
    assert decision.kind is DecisionKind.ALLOW
    assert decision.effective_risk_level is RiskLevel.READ_ONLY


def _project() -> Project:
    now = datetime.now(UTC)
    return Project(
        id="proj_vf",
        name="VisualForge",
        slug="visualforge",
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


def test_exact_telegram_workflow_needs_no_approval() -> None:
    goal = (
        'Dùng VisualForge tạo prompt ảnh serum, text "GIẢM 50%". '
        "Không gọi OpenClaw. Không sửa file, config hoặc service."
    )
    _, capability = _capability(goal)
    project = _project()
    request = CoreRequest(
        text=goal,
        channel="telegram",
        actor="telegram:test",
        project_id=project.id,
        source_chat_id="chat",
        source_session_id="session",
        source_message_id="message",
    )
    envelope = WorkflowResolver().resolve(
        request=request,
        request_id="req_vf",
        normalized_text=goal,
        capability=capability.capability,
        project=project,
    )
    assert envelope.risk_level is RiskLevel.READ_ONLY
    assert envelope.approval_required is False
    assert envelope.policy_decision is DecisionKind.ALLOW
    assert envelope.mode == "quick"

def test_visual_image_generation_is_owner_allowed_and_bounded() -> None:
    action, risk, constraints = WorkflowResolver._action(
        "Tạo ảnh quảng cáo serum 9:16",
        CapabilityKind.VISUAL_IMAGE_GENERATE,
    )

    assert action == "generate_visual_image"
    assert risk is RiskLevel.READ_ONLY
    assert "one_image_max" in constraints
    assert "subscription_quota_only" in constraints
    assert "no_paid_fallback" in constraints
    assert "retry_delivery_without_regeneration" in constraints

    decision = PolicyEngine.with_default_roots().evaluate(
        PolicyAction(name=action, declared_risk_level=risk),
    )
    assert decision.kind is DecisionKind.ALLOW
    assert decision.effective_risk_level is RiskLevel.READ_ONLY


def test_image_for_facebook_post_auto_executes_bounded() -> None:
    goal = "Tạo 1 ảnh minh hoạ để đăng Facebook theo phương án mình vừa bàn."
    _, capability = _capability(goal)
    assert capability.capability is CapabilityKind.VISUAL_IMAGE_GENERATE
    project = _project()
    envelope = WorkflowResolver().resolve(
        request=CoreRequest(
            text=goal, channel="telegram", actor="telegram:test",
            project_id=project.id, source_chat_id="chat",
            source_session_id="session", source_message_id="message-image-post",
        ),
        request_id="req_image_post", normalized_text=goal,
        capability=capability.capability, project=project,
    )
    assert envelope.approval_required is False
    assert envelope.policy_decision is DecisionKind.ALLOW
    for item in ("one_image_max", "subscription_quota_only", "no_paid_fallback",
                 "retry_delivery_without_regeneration"):
        assert item in envelope.constraints
