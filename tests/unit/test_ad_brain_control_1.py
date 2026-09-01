from app.capabilities import CapabilityKind, CapabilityRouter
from app.orchestration.workflow import WorkflowResolver
from app.policy import RiskLevel
from app.routing import FastRoute, FastRouter


def _route(text: str):
    router = FastRouter()
    decision = router.route(text)
    capability = CapabilityRouter().route(decision, text)
    return decision, capability


def test_operational_guidance_about_openclaw_is_not_direct_conversation() -> None:
    decision, capability = _route("Mở Chrome thông qua OpenClaw như nào?")

    assert decision.route is FastRoute.WORKFLOW
    assert capability.capability is CapabilityKind.SYSTEM_OPERATION


def test_runtime_location_question_is_not_direct_conversation() -> None:
    decision, capability = _route("OpenClaw của anh đang chạy ở đâu?")

    assert decision.route is FastRoute.WORKFLOW
    assert capability.capability is CapabilityKind.SYSTEM_OPERATION


def test_request_for_openclaw_command_is_not_direct_conversation() -> None:
    decision, capability = _route("Cho anh lệnh kiểm tra OpenClaw trong WSL")

    assert decision.route is FastRoute.WORKFLOW
    assert capability.capability is CapabilityKind.SYSTEM_OPERATION


def test_operational_guidance_is_read_only_runtime_verification() -> None:
    action, risk, constraints = WorkflowResolver._action(
        "Mở Chrome thông qua OpenClaw như nào?",
        CapabilityKind.SYSTEM_OPERATION,
    )

    assert action == "view_status"
    assert risk is RiskLevel.READ_ONLY
    assert "read_only" in constraints
    assert "verify_runtime_before_guidance" in constraints
    assert "no_unverified_operational_commands" in constraints
    assert "no_file_changes" in constraints
    assert "no_config_changes" in constraints
    assert "no_service_restart" in constraints


def test_casual_conversation_stays_direct() -> None:
    decision, capability = _route("alo")

    assert decision.route is FastRoute.DIRECT
    assert capability.capability is CapabilityKind.CONVERSATIONAL_RESPONSE


def test_operational_guidance_with_positive_mutation_never_becomes_readonly_view_status() -> None:
    action, risk, _ = WorkflowResolver._action(
        "Hướng dẫn anh kiểm tra service; rồi deploy bản này.",
        CapabilityKind.SYSTEM_OPERATION,
    )

    assert action == "workflow_system_operation"
    assert risk is None


def test_operational_guidance_unknown_followup_action_never_becomes_readonly() -> None:
    action, risk, _ = WorkflowResolver._action(
        "Tell me how to check Core health, then rotate credentials.",
        CapabilityKind.SYSTEM_OPERATION,
    )

    assert action == "workflow_system_operation"
    assert risk is None
