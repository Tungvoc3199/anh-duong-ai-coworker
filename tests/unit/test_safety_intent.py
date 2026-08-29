import pytest

from app.safety_intent import SafetyConstraint, analyze_safety_intent


@pytest.mark.parametrize(
    ("text", "constraint"),
    [
        ("Kiểm tra bằng chế độ chỉ đọc.", SafetyConstraint.READ_ONLY),
        ("Không sửa file.", SafetyConstraint.NO_FILE_CHANGES),
        ("Không thay đổi tệp nào.", SafetyConstraint.NO_FILE_CHANGES),
        ("Không sửa cấu hình.", SafetyConstraint.NO_CONFIG_CHANGES),
        ("Không đổi config.", SafetyConstraint.NO_CONFIG_CHANGES),
        ("Không sửa file hoặc config.", SafetyConstraint.NO_CONFIG_CHANGES),
        ("Không restart service.", SafetyConstraint.NO_SERVICE_RESTART),
        ("Không khởi động lại dịch vụ.", SafetyConstraint.NO_SERVICE_RESTART),
        ("Không chạy Git.", SafetyConstraint.NO_GIT),
        ("Không dùng git.", SafetyConstraint.NO_GIT),
        ("Không gọi OpenClaw hoặc model.", SafetyConstraint.NO_OPENCLAW),
        ("Không gọi OpenClaw hoặc model.", SafetyConstraint.NO_MODEL),
        ("Không install package.", SafetyConstraint.NO_PACKAGE_INSTALL),
        ("Không cài đặt gói nào.", SafetyConstraint.NO_PACKAGE_INSTALL),
        ("Không deploy bản mới.", SafetyConstraint.NO_DEPLOY),
        ("Không triển khai gì.", SafetyConstraint.NO_DEPLOY),
        ("Không thay đổi hệ thống.", SafetyConstraint.NO_SYSTEM_MUTATION),
        ("No system mutation.", SafetyConstraint.NO_SYSTEM_MUTATION),
    ],
)
def test_natural_safety_paraphrases_normalize_to_typed_constraint(
    text: str,
    constraint: SafetyConstraint,
) -> None:
    intent = analyze_safety_intent(text)

    assert constraint in intent.constraints


@pytest.mark.parametrize(
    ("text", "constraint"),
    [
        ("Hãy sửa config này.", SafetyConstraint.NO_CONFIG_CHANGES),
        ("Hãy restart service.", SafetyConstraint.NO_SERVICE_RESTART),
        ("Chạy Git status đi.", SafetyConstraint.NO_GIT),
        ("Dùng model để trả lời.", SafetyConstraint.NO_MODEL),
        ("Deploy bản này.", SafetyConstraint.NO_DEPLOY),
    ],
)
def test_positive_execution_language_is_not_misread_as_safety_constraint(
    text: str,
    constraint: SafetyConstraint,
) -> None:
    intent = analyze_safety_intent(text)

    assert constraint not in intent.constraints


def test_negation_scope_does_not_cross_contrast_boundary() -> None:
    intent = analyze_safety_intent("Không sửa file, nhưng hãy đổi config.")

    assert SafetyConstraint.NO_FILE_CHANGES in intent.constraints
    assert SafetyConstraint.NO_CONFIG_CHANGES not in intent.constraints
