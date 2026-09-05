from app.capabilities.intent_contract import (
    VisualDelivery,
    VisualExternalEffect,
    VisualPurpose,
    build_visual_intent_contract,
)


def test_contract_separates_social_purpose_from_source_delivery() -> None:
    contract = build_visual_intent_contract(
        "Tạo ảnh để đăng Facebook. Chỉ tạo và gửi đúng 1 ảnh, không gửi trùng."
    )
    assert contract.purpose == (VisualPurpose.SOCIAL_CONTENT,)
    assert contract.delivery is VisualDelivery.SOURCE_CHANNEL
    assert contract.external_effects == ()


def test_contract_marks_explicit_publish_effect() -> None:
    contract = build_visual_intent_contract("Tạo ảnh rồi đăng nó lên Facebook cho anh.")
    assert VisualExternalEffect.PUBLISH in contract.external_effects


def test_contract_marks_third_party_send_but_not_source_return() -> None:
    external = build_visual_intent_contract("Tạo ảnh rồi gửi cho Tuấn qua Telegram.")
    source = build_visual_intent_contract("Tạo ảnh xong gửi lại đây.")
    assert VisualExternalEffect.THIRD_PARTY_SEND in external.external_effects
    assert source.delivery is VisualDelivery.SOURCE_CHANNEL
    assert source.external_effects == ()
