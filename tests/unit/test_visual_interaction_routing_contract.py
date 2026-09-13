import pytest
from pydantic import ValidationError

from app.capabilities import CapabilityKind, CapabilityRouter
from app.orchestration.models import CoreRequest
from app.routing import FastRoute, FastRouter
from app.visual_interaction import (
    VisualImageSource,
    VisualOperation,
    build_visual_interaction_contract,
)

REF = "media://inbound/visual---11111111-1111-4111-8111-111111111111.jpg"


def _contract(text: str, source: VisualImageSource, reference: str | None = None):
    result = build_visual_interaction_contract(
        text,
        image_source=source,
        reference_image=reference,
    )
    assert result is not None
    return result


def test_core_request_accepts_separate_image_source_and_reference() -> None:
    request = CoreRequest(
        text="phân tích ảnh này",
        image_source=VisualImageSource.CURRENT_UPLOAD,
        reference_image=REF,
    )
    assert request.image_source is VisualImageSource.CURRENT_UPLOAD
    assert request.reference_image == REF


def test_core_request_rejects_source_reference_mismatch() -> None:
    with pytest.raises(ValidationError):
        CoreRequest(text="phân tích ảnh này", image_source=VisualImageSource.CURRENT_UPLOAD)
    with pytest.raises(ValidationError):
        CoreRequest(text="phân tích ảnh này", reference_image=REF)


def test_visual_analysis_contract_routes_direct() -> None:
    text = "phân tích lỗi trong ảnh, k tạo lại ảnh"
    visual = _contract(text, VisualImageSource.REPLIED_IMAGE, REF)
    decision = FastRouter().route(text, visual_interaction=visual)
    assert visual.operation is VisualOperation.ANALYZE
    assert decision.route is FastRoute.DIRECT
    assert decision.rule_id == "routing.direct.visual_analysis"


def test_visual_generation_contract_routes_workflow() -> None:
    text = "tạo một cô gái mặc váy vàng"
    visual = _contract(text, VisualImageSource.NONE)
    decision = FastRouter().route(text, visual_interaction=visual)
    assert decision.route is FastRoute.WORKFLOW
    assert decision.rule_id == "routing.workflow.visual_operation"


def test_visual_edit_without_target_routes_direct_clarification() -> None:
    text = "đổi váy vàng"
    visual = _contract(text, VisualImageSource.NONE)
    decision = FastRouter().route(text, visual_interaction=visual)
    assert visual.clarification_required is True
    assert decision.route is FastRoute.DIRECT
    assert decision.rule_id == "routing.direct.visual_clarification"


def test_visual_analysis_maps_to_read_only_capability() -> None:
    text = "e có thấy cái ảnh nó sai cái gì k?"
    visual = _contract(text, VisualImageSource.REPLIED_IMAGE, REF)
    route = FastRouter().route(text, visual_interaction=visual)
    capability = CapabilityRouter().route(route, text, visual_interaction=visual)
    assert route.route is FastRoute.DIRECT
    assert capability.capability is CapabilityKind.VISUAL_ANALYSIS
    assert capability.reason_code == "capability.direct.visual_analysis"


def test_visual_generation_keeps_existing_executor_capability() -> None:
    text = "tạo một cô gái mặc váy vàng"
    visual = _contract(text, VisualImageSource.NONE)
    route = FastRouter().route(text, visual_interaction=visual)
    capability = CapabilityRouter().route(route, text, visual_interaction=visual)
    assert capability.capability is CapabilityKind.VISUAL_IMAGE_GENERATE
    assert capability.reason_code == "capability.workflow.visual_image_generate"


def test_visual_turn_capability_is_recomputed_from_current_contract() -> None:
    generate_text = "tạo một cô gái mặc váy vàng"
    generate = _contract(generate_text, VisualImageSource.NONE)
    generate_route = FastRouter().route(generate_text, visual_interaction=generate)
    assert CapabilityRouter().route(
        generate_route,
        generate_text,
        visual_interaction=generate,
    ).capability is CapabilityKind.VISUAL_IMAGE_GENERATE

    analyze_text = "e có thấy cái ảnh nó sai cái gì k?"
    analyze = _contract(analyze_text, VisualImageSource.REPLIED_IMAGE, REF)
    analyze_route = FastRouter().route(analyze_text, visual_interaction=analyze)
    assert CapabilityRouter().route(
        analyze_route,
        analyze_text,
        visual_interaction=analyze,
    ).capability is CapabilityKind.VISUAL_ANALYSIS
