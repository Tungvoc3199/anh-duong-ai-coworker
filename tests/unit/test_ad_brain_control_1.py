from app.capabilities import CapabilityKind, CapabilityRouter
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


def test_casual_conversation_stays_direct() -> None:
    decision, capability = _route("alo")

    assert decision.route is FastRoute.DIRECT
    assert capability.capability is CapabilityKind.CONVERSATIONAL_RESPONSE
