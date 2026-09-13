import pytest

from app.visual_interaction import (
    VisualConstraint,
    VisualImageRole,
    VisualImageSource,
    VisualOperation,
    VisualOutput,
    VisualSideEffect,
    build_visual_interaction_contract,
)

REF = "media://inbound/visual---11111111-1111-4111-8111-111111111111.jpg"


def _build(
    text: str,
    *,
    source: VisualImageSource = VisualImageSource.NONE,
    reference: str | None = None,
):
    contract = build_visual_interaction_contract(
        text,
        image_source=source,
        reference_image=reference,
    )
    assert contract is not None
    return contract


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("e có thấy cái ảnh nó sai cái gì k?", VisualOperation.ANALYZE),
        ("ảnh đấy e, e xem những điều a nói có đúng k", VisualOperation.ANALYZE),
        ("phân tích lỗi trong ảnh, k tạo lại ảnh", VisualOperation.ANALYZE),
        ("e phân tích lỗi sai trong ảnh a gửi đi", VisualOperation.ANALYZE),
        ("khoanh hai chỗ sai", VisualOperation.ANNOTATE),
        ("sửa hai chỗ sai đó", VisualOperation.EDIT),
        ("đổi váy vàng", VisualOperation.EDIT),
        ("tạo một cô gái mặc váy vàng", VisualOperation.GENERATE),
        ("đừng sửa gì, chỉ nhận xét", VisualOperation.ANALYZE),
    ],
)
def test_golden_visual_operations(text: str, expected: VisualOperation) -> None:
    source = (
        VisualImageSource.REPLIED_IMAGE
        if expected in {VisualOperation.ANALYZE, VisualOperation.ANNOTATE, VisualOperation.EDIT}
        else VisualImageSource.NONE
    )
    reference = REF if source is not VisualImageSource.NONE else None
    contract = _build(text, source=source, reference=reference)
    assert contract.operation is expected


def test_analysis_with_negated_generation_is_hard_no_generate() -> None:
    contract = _build(
        "phân tích lỗi trong ảnh, k tạo lại ảnh",
        source=VisualImageSource.CURRENT_UPLOAD,
        reference=REF,
    )
    assert contract.operation is VisualOperation.ANALYZE
    assert VisualConstraint.NO_GENERATE in contract.constraints
    assert contract.output is VisualOutput.TEXT
    assert contract.side_effect is VisualSideEffect.NONE


def test_no_edit_comment_is_analysis_with_hard_no_edit() -> None:
    contract = _build(
        "đừng sửa gì, chỉ nhận xét",
        source=VisualImageSource.REPLIED_IMAGE,
        reference=REF,
    )
    assert contract.operation is VisualOperation.ANALYZE
    assert VisualConstraint.NO_EDIT in contract.constraints
    assert contract.image_role is VisualImageRole.EVIDENCE


def test_new_generation_does_not_require_an_image() -> None:
    contract = _build("tạo một cô gái mặc váy vàng")
    assert contract.operation is VisualOperation.GENERATE
    assert contract.output is VisualOutput.IMAGE
    assert contract.image_source is VisualImageSource.NONE
    assert contract.image_role is None
    assert contract.clarification_required is False


def test_style_reference_generation_keeps_reference_role() -> None:
    contract = _build(
        "tạo ảnh mới giống phong cách ảnh này",
        source=VisualImageSource.REPLIED_IMAGE,
        reference=REF,
    )
    assert contract.operation is VisualOperation.GENERATE
    assert contract.image_role is VisualImageRole.STYLE_REFERENCE
    assert contract.reference_image == REF
    assert contract.clarification_required is False


def test_edit_without_target_requires_clarification_instead_of_guessing() -> None:
    contract = _build("đổi váy vàng")
    assert contract.operation is VisualOperation.EDIT
    assert contract.image_source is VisualImageSource.NONE
    assert contract.reference_image is None
    assert contract.clarification_required is True


def test_ambiguous_target_requires_clarification_and_carries_no_reference() -> None:
    contract = _build("sửa hai chỗ sai đó", source=VisualImageSource.AMBIGUOUS)
    assert contract.operation is VisualOperation.EDIT
    assert contract.clarification_required is True
    assert contract.reference_image is None


def test_diacritic_collision_dung_is_not_action_alias_dung() -> None:
    contract = _build(
        "ảnh đấy e, e xem những điều a nói có đúng k",
        source=VisualImageSource.REPLIED_IMAGE,
        reference=REF,
    )
    assert contract.operation is VisualOperation.ANALYZE
    assert contract.operation is not VisualOperation.GENERATE


def test_question_rejecting_regeneration_is_read_only() -> None:
    contract = _build(
        "a đang hỏi e chứ k bảo e tạo lại ảnh",
        source=VisualImageSource.REPLIED_IMAGE,
        reference=REF,
    )
    assert contract.operation in {VisualOperation.ANALYZE, VisualOperation.CONVERSE}
    assert VisualConstraint.NO_GENERATE in contract.constraints
    assert contract.output is VisualOutput.TEXT


def test_analysis_uses_evidence_and_extract_uses_data_source() -> None:
    analyzed = _build("phân tích ảnh này", source=VisualImageSource.CURRENT_UPLOAD, reference=REF)
    extracted = _build(
        "trích xuất chữ trong ảnh",
        source=VisualImageSource.CURRENT_UPLOAD,
        reference=REF,
    )
    assert analyzed.image_role is VisualImageRole.EVIDENCE
    assert extracted.operation is VisualOperation.EXTRACT
    assert extracted.image_role is VisualImageRole.DATA_SOURCE
    assert extracted.output is VisualOutput.STRUCTURED_DATA


def test_non_visual_turn_returns_none() -> None:
    assert build_visual_interaction_contract("xin chào em") is None


def test_concrete_image_source_requires_managed_reference() -> None:
    with pytest.raises(ValueError):
        build_visual_interaction_contract(
            "phân tích ảnh này",
            image_source=VisualImageSource.CURRENT_UPLOAD,
        )


def test_none_or_ambiguous_source_rejects_reference() -> None:
    with pytest.raises(ValueError):
        build_visual_interaction_contract(
            "phân tích ảnh này",
            image_source=VisualImageSource.NONE,
            reference_image=REF,
        )
    with pytest.raises(ValueError):
        build_visual_interaction_contract(
            "phân tích ảnh này",
            image_source=VisualImageSource.AMBIGUOUS,
            reference_image=REF,
        )


def test_raw_instruction_is_preserved_verbatim() -> None:
    text = "  Phân tích ảnh này, k tạo lại ảnh.  "
    contract = _build(text, source=VisualImageSource.CURRENT_UPLOAD, reference=REF)
    assert contract.raw_instruction == text


def test_visual_prompt_compose_stays_outside_visual_interaction_contract() -> None:
    assert build_visual_interaction_contract("Tạo prompt ảnh poster khai trương.") is None


def test_social_destination_as_generation_purpose_is_not_external_action() -> None:
    contract = _build("Tạo ảnh quảng cáo để đăng Facebook.")
    assert contract.operation is VisualOperation.GENERATE
    assert contract.side_effect is VisualSideEffect.NONE


def test_explicit_publish_after_generation_is_external_action() -> None:
    contract = _build("Tạo ảnh rồi đăng Facebook cho anh.")
    assert contract.operation is VisualOperation.EXTERNAL_ACTION
    assert contract.side_effect is VisualSideEffect.PUBLISH
