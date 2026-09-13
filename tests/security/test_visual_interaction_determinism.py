from app.visual_interaction import (
    VisualConstraint,
    VisualImageSource,
    VisualOperation,
    build_visual_interaction_contract,
)

REF = "media://inbound/visual---11111111-1111-4111-8111-111111111111.jpg"


def test_classifier_is_deterministic_for_same_semantic_inputs() -> None:
    kwargs = {"image_source": VisualImageSource.REPLIED_IMAGE, "reference_image": REF}
    first = build_visual_interaction_contract("phân tích lỗi trong ảnh, k tạo lại ảnh", **kwargs)
    second = build_visual_interaction_contract("phân tích lỗi trong ảnh, k tạo lại ảnh", **kwargs)
    assert first == second


def test_negation_is_resolved_before_positive_generation_signal() -> None:
    result = build_visual_interaction_contract(
        "không tạo ảnh mới, chỉ phân tích ảnh này",
        image_source=VisualImageSource.REPLIED_IMAGE,
        reference_image=REF,
    )
    assert result is not None
    assert result.operation is VisualOperation.ANALYZE
    assert VisualConstraint.NO_GENERATE in result.constraints


def test_previous_generation_state_is_not_a_classifier_input() -> None:
    result = build_visual_interaction_contract(
        "e có thấy cái ảnh nó sai cái gì k?",
        image_source=VisualImageSource.REPLIED_IMAGE,
        reference_image=REF,
    )
    assert result is not None
    assert result.operation is VisualOperation.ANALYZE
