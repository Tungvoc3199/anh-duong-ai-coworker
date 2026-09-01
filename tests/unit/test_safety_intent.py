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


@pytest.mark.parametrize(
    "text",
    [
        (
            "Kiểm tra tình trạng Ánh Dương Core health/ready, chỉ đọc, "
            "không restart service, nhưng deploy bản mới."
        ),
        (
            "Kiểm tra tình trạng Ánh Dương Core health/ready, chỉ đọc, "
            "không restart service, nhưng restart nếu lỗi."
        ),
        (
            "Kiểm tra tình trạng Ánh Dương Core health/ready, chỉ đọc, "
            "không restart service, nhưng install package nếu lỗi."
        ),
        (
            "Kiểm tra tình trạng Ánh Dương Core health/ready, chỉ đọc, "
            "không restart service, hãy sửa config nếu lỗi."
        ),
    ],
)
def test_readonly_status_intent_detects_unnegated_side_effects(text: str) -> None:
    intent = analyze_safety_intent(text)
    assert intent.unnegated_mutation is True


SAFE_CORE_STATUS_PARAPHRASES = (
    (
        "Dương, kiểm tra tình trạng hệ thống Ánh Dương hiện tại giúp anh. "
        "Kiểm tra Core service, health, ready và database quick_check; "
        "chỉ đọc, không sửa hay restart gì."
    ),
    (
        "Xác minh trạng thái Ánh Dương Core: health và ready. "
        "Chỉ đọc, không thay đổi gì, không khởi động lại dịch vụ."
    ),
    (
        "Xem giúp anh status Ánh Dương Core, health/ready hiện có ổn không. "
        "Chỉ xem thôi, không sửa gì và không restart service."
    ),
    ("Check status Anh Duong Core health/ready. Read only, no changes and no restart."),
    (
        "Kiểm tra tình trạng Ánh Dương Core health/ready bằng chế độ chỉ đọc. "
        "Không install, deploy hoặc thay đổi hệ thống. Gửi kết quả cho anh."
    ),
)


@pytest.mark.parametrize("text", SAFE_CORE_STATUS_PARAPHRASES)
def test_core_readonly_status_paraphrase_matrix_is_safe(text: str) -> None:
    from app.safety_intent import is_read_only_core_status_intent

    intent = analyze_safety_intent(text)

    assert intent.unnegated_mutation is False
    assert is_read_only_core_status_intent(intent) is True


@pytest.mark.parametrize(
    "text",
    [
        (
            "Kiểm tra tình trạng Ánh Dương Core health/ready, chỉ đọc, "
            "không restart service, sửa config nếu lỗi."
        ),
        (
            "Kiểm tra tình trạng Ánh Dương Core health/ready, chỉ đọc, "
            "không restart service và sửa config nếu lỗi."
        ),
        (
            "Kiểm tra tình trạng Ánh Dương Core health/ready, chỉ đọc, "
            "không restart service, rồi deploy bản mới."
        ),
        (
            "Kiểm tra tình trạng Ánh Dương Core health/ready, chỉ đọc, "
            "không restart service. Deploy bản mới nếu lỗi."
        ),
        (
            "Check status Anh Duong Core health/ready, read only, "
            "no restart, then install package if unhealthy."
        ),
        (
            "Kiểm tra tình trạng Ánh Dương Core health/ready, chỉ đọc, "
            "không restart service, gửi email cho admin nếu lỗi."
        ),
    ],
)
def test_core_readonly_status_adversarial_matrix_fails_closed(text: str) -> None:
    from app.safety_intent import is_read_only_core_status_intent

    intent = analyze_safety_intent(text)

    assert intent.unnegated_mutation is True
    assert is_read_only_core_status_intent(intent) is False


@pytest.mark.parametrize(
    "text",
    [
        "Chỉ đọc, không sửa gì.",
        "Chỉ đọc, không thay đổi gì.",
        "Chỉ đọc, không sửa hay restart gì.",
        "Read only, no changes.",
    ],
)
def test_broad_no_change_language_produces_system_mutation_boundary(text: str) -> None:
    intent = analyze_safety_intent(text)

    assert SafetyConstraint.READ_ONLY in intent.constraints
    assert SafetyConstraint.NO_SYSTEM_MUTATION in intent.constraints


@pytest.mark.parametrize(
    "suffix",
    [
        "chạy lệnh kiểm tra sâu nếu lỗi",
        "gọi OpenClaw nếu lỗi",
        "commit thay đổi nếu lỗi",
        "upload log nếu lỗi",
        "cập nhật config nếu lỗi",
        "gửi Slack cho admin nếu lỗi",
    ],
)
def test_readonly_status_rejects_cross_capability_side_effects(suffix: str) -> None:
    from app.safety_intent import is_read_only_core_status_intent

    text = (
        "Kiểm tra tình trạng Ánh Dương Core health/ready, chỉ đọc, "
        f"không restart service, {suffix}."
    )
    intent = analyze_safety_intent(text)

    assert intent.unnegated_mutation is True
    assert is_read_only_core_status_intent(intent) is False


def test_harmless_result_delivery_does_not_become_mutation() -> None:
    from app.safety_intent import is_read_only_core_status_intent

    text = (
        "Xem tình trạng Ánh Dương Core health/ready, chỉ xem thôi, "
        "đừng sửa gì và đừng restart service. Gửi kết quả cho anh."
    )
    intent = analyze_safety_intent(text)

    assert intent.unnegated_mutation is False
    assert SafetyConstraint.NO_SYSTEM_MUTATION in intent.constraints
    assert SafetyConstraint.NO_SERVICE_RESTART in intent.constraints
    assert is_read_only_core_status_intent(intent) is True


@pytest.mark.parametrize("observation", ["Kiểm tra", "Xác minh", "Xem"])
@pytest.mark.parametrize("status_word", ["trạng thái", "tình trạng", "status"])
@pytest.mark.parametrize(
    "boundary",
    [
        "chỉ đọc, không sửa hay restart gì",
        "chỉ đọc, không thay đổi gì, không restart service",
        "chỉ xem thôi, đừng sửa gì, đừng restart service",
    ],
)
def test_readonly_core_status_generated_safe_matrix(
    observation: str,
    status_word: str,
    boundary: str,
) -> None:
    from app.safety_intent import is_read_only_core_status_intent

    text = f"{observation} {status_word} Ánh Dương Core health/ready; {boundary}."
    intent = analyze_safety_intent(text)

    assert intent.unnegated_mutation is False
    assert is_read_only_core_status_intent(intent) is True


@pytest.mark.parametrize("separator", [", ", "; ", ". ", "\n"])
@pytest.mark.parametrize(
    "effect",
    [
        "sửa config nếu lỗi",
        "restart service nếu lỗi",
        "deploy bản mới",
        "install package",
        "chạy lệnh kiểm tra sâu",
        "gọi OpenClaw",
        "upload log",
        "gửi email cho admin",
    ],
)
def test_readonly_core_status_generated_adversarial_matrix(
    separator: str,
    effect: str,
) -> None:
    from app.safety_intent import is_read_only_core_status_intent

    text = (
        "Kiểm tra tình trạng Ánh Dương Core health/ready; "
        "chỉ đọc, không sửa hay restart gì"
        f"{separator}{effect}."
    )
    intent = analyze_safety_intent(text)

    assert intent.unnegated_mutation is True
    assert is_read_only_core_status_intent(intent) is False


@pytest.mark.parametrize(
    "text",
    [
        (
            "Kiểm tra tình trạng Ánh Dương Core health/ready, chỉ đọc, "
            "không restart service và nếu lỗi thì deploy bản mới."
        ),
        (
            "Kiểm tra tình trạng Ánh Dương Core health/ready, chỉ đọc, "
            "không restart service and if unhealthy then install package."
        ),
        (
            "Kiểm tra tình trạng Ánh Dương Core health/ready, chỉ đọc, "
            "không restart service và nếu lỗi thì chạy lệnh kiểm tra sâu."
        ),
    ],
)
def test_conditional_side_effect_after_negation_is_never_swallowed(text: str) -> None:
    from app.safety_intent import is_read_only_core_status_intent

    intent = analyze_safety_intent(text)

    assert intent.unnegated_mutation is True
    assert is_read_only_core_status_intent(intent) is False


@pytest.mark.parametrize(
    "text",
    [
        (
            "Kiểm tra tình trạng Ánh Dương Core health/ready, chỉ đọc, "
            "không sửa gì và nếu lỗi deploy bản mới."
        ),
        (
            "Check status Anh Duong Core health/ready, read only, "
            "no changes and if unhealthy install package."
        ),
        (
            "Kiểm tra tình trạng Ánh Dương Core health/ready, chỉ đọc, "
            "không sửa gì nếu lỗi thì deploy bản mới."
        ),
        (
            "Kiểm tra tình trạng Ánh Dương Core health/ready, chỉ đọc, "
            "không restart service và nếu lỗi deploy bản mới."
        ),
    ],
)
def test_conditional_side_effect_without_explicit_then_fails_closed(text: str) -> None:
    from app.safety_intent import is_read_only_core_status_intent

    intent = analyze_safety_intent(text)

    assert intent.unnegated_mutation is True
    assert is_read_only_core_status_intent(intent) is False


@pytest.mark.parametrize(
    "text",
    [
        (
            "Kiểm tra tình trạng Ánh Dương Core health/ready, chỉ đọc, "
            "không sửa gì: deploy bản mới nếu lỗi."
        ),
        (
            "Kiểm tra tình trạng Ánh Dương Core health/ready, chỉ đọc, "
            "không sửa gì — restart service nếu lỗi."
        ),
        (
            "Kiểm tra tình trạng Ánh Dương Core health/ready, chỉ đọc, "
            "không sửa gì / install package nếu lỗi."
        ),
        (
            "Kiểm tra tình trạng Ánh Dương Core health/ready, chỉ đọc, "
            "không sửa gì và sau đó deploy bản mới nếu lỗi."
        ),
        (
            "Kiểm tra tình trạng Ánh Dương Core health/ready, chỉ đọc, "
            "không sửa gì và tiếp theo chạy lệnh sâu."
        ),
    ],
)
def test_side_effect_separator_variants_fail_closed(text: str) -> None:
    from app.safety_intent import is_read_only_core_status_intent

    intent = analyze_safety_intent(text)

    assert intent.unnegated_mutation is True
    assert is_read_only_core_status_intent(intent) is False


@pytest.mark.parametrize(
    "effect",
    [
        "stop service nếu lỗi",
        "start service nếu lỗi",
        "disable service nếu lỗi",
        "enable service nếu lỗi",
        "reload service nếu lỗi",
        "reboot máy nếu lỗi",
        "shutdown máy nếu lỗi",
        "kill process nếu lỗi",
        "dừng service nếu lỗi",
        "bật service nếu lỗi",
        "tắt service nếu lỗi",
    ],
)
def test_service_lifecycle_effects_are_mutations(effect: str) -> None:
    text = f"Kiểm tra trạng thái Gateway health/ready, chỉ đọc, không sửa gì, nhưng {effect}."
    intent = analyze_safety_intent(text)

    assert intent.unnegated_mutation is True


@pytest.mark.parametrize(
    "text",
    [
        (
            "Xác minh trạng thái Ánh Dương Core health/ready. "
            "Chỉ đọc, không thay đổi gì, không restart. Then remove the database."
        ),
        (
            "Check status Anh Duong Core health/ready. "
            "Read only, no changes and no restart. Then rotate credentials."
        ),
        (
            "Kiểm tra tình trạng Ánh Dương Core health/ready. "
            "Chỉ đọc, không sửa gì, rồi format disk nếu lỗi."
        ),
        (
            "Check status Anh Duong Core health/ready. "
            "Read only, no changes and no restart. Then scale the service."
        ),
    ],
)
def test_unknown_post_readonly_action_fails_closed(text: str) -> None:
    from app.safety_intent import is_read_only_core_status_intent

    intent = analyze_safety_intent(text)

    assert intent.unnegated_mutation is True
    assert is_read_only_core_status_intent(intent) is False


@pytest.mark.parametrize(
    "text",
    [
        (
            "Kiểm tra tình trạng Ánh Dương Core health/ready. "
            "Chỉ đọc, không sửa gì. Gửi kết quả cho anh."
        ),
        (
            "Kiểm tra tình trạng Ánh Dương Core health/ready. "
            "Chỉ đọc, không sửa gì. Chỉ báo thành công khi có bằng chứng thật."
        ),
        (
            "Kiểm tra tình trạng Ánh Dương Core health/ready. "
            "Chỉ đọc, không sửa gì. Xác minh thêm database quick_check."
        ),
    ],
)
def test_harmless_post_readonly_clauses_remain_allowed(text: str) -> None:
    from app.safety_intent import is_read_only_core_status_intent

    intent = analyze_safety_intent(text)

    assert intent.unnegated_mutation is False
    assert is_read_only_core_status_intent(intent) is True


@pytest.mark.parametrize(
    "text",
    [
        (
            "Check status Anh Duong Core health/ready. "
            "Read only, no changes except deploy if unhealthy, no restart."
        ),
        (
            "Kiểm tra tình trạng Ánh Dương Core health/ready. "
            "Chỉ đọc, không thay đổi gì ngoại trừ deploy nếu lỗi, không restart."
        ),
    ],
)
def test_readonly_exception_clause_preserves_positive_mutation(text: str) -> None:
    from app.safety_intent import is_read_only_core_status_intent

    intent = analyze_safety_intent(text)

    assert intent.unnegated_mutation is True
    assert is_read_only_core_status_intent(intent) is False


@pytest.mark.parametrize(
    "text",
    [
        (
            "Rotate credentials, then check status Anh Duong Core health/ready. "
            "Read only, no changes and no restart."
        ),
        (
            "Format disk, rồi kiểm tra tình trạng Ánh Dương Core health/ready. "
            "Chỉ đọc, không sửa gì và không restart."
        ),
    ],
)
def test_unknown_action_before_readonly_boundary_fails_closed(text: str) -> None:
    from app.safety_intent import is_read_only_core_status_intent

    intent = analyze_safety_intent(text)

    assert intent.unnegated_mutation is True
    assert is_read_only_core_status_intent(intent) is False


@pytest.mark.parametrize(
    "text",
    [
        "Check status Anh Duong Core health/ready. Read only rotate credentials; no changes.",
        "Kiểm tra tình trạng Ánh Dương Core health/ready. Chỉ đọc format disk; không sửa gì.",
    ],
)
def test_unknown_action_in_same_readonly_clause_fails_closed(text: str) -> None:
    from app.safety_intent import is_read_only_core_status_intent

    intent = analyze_safety_intent(text)

    assert intent.unnegated_mutation is True
    assert is_read_only_core_status_intent(intent) is False


@pytest.mark.parametrize(
    "text",
    [
        (
            "Check status Anh Duong Core health/ready. Read only, no changes. "
            "Do not restart before deploy new version."
        ),
        (
            "Check status Anh Duong Core health/ready. Read only, no changes. "
            "No restart while install package."
        ),
        (
            "Kiểm tra trạng thái Ánh Dương Core health/ready. Chỉ đọc, không sửa gì. "
            "Không restart trước khi deploy bản mới."
        ),
        (
            "Check status Anh Duong Core health/ready. Read only, no changes and no restart. "
            "Report results after rotating credentials."
        ),
        (
            "Check status Anh Duong Core health/ready. Read only, no changes and no restart. "
            "Return result after format disk."
        ),
    ],
)
def test_temporal_connector_never_hides_readonly_side_effect(text: str) -> None:
    from app.safety_intent import is_read_only_core_status_intent

    intent = analyze_safety_intent(text)

    assert intent.unnegated_mutation is True
    assert is_read_only_core_status_intent(intent) is False


@pytest.mark.parametrize(
    "text",
    [
        "Check status Anh Duong Core health/ready. Rotate credentials read only. No changes.",
        "Check status Anh Duong Core health/ready. Format disk readonly. No changes.",
        (
            "Check status Anh Duong Core health/ready. Rotate credentials to report results. "
            "Read only, no changes and no restart."
        ),
        (
            "Read only. No commands, no file changes, no config changes, no restart. "
            "Rotate credentials."
        ),
    ],
)
def test_unknown_action_anywhere_in_readonly_request_fails_closed(text: str) -> None:
    intent = analyze_safety_intent(text)
    assert intent.unnegated_mutation is True


@pytest.mark.parametrize(
    "text",
    [
        (
            "Check status Anh Duong Core health/ready. Read only, no changes and no restart. "
            "Please provide the results."
        ),
        (
            "Check status Anh Duong Core health/ready. Read only, no changes and no restart. "
            "Please show me the results."
        ),
    ],
)
def test_polite_report_followups_remain_readonly(text: str) -> None:
    intent = analyze_safety_intent(text)
    assert intent.unnegated_mutation is False


@pytest.mark.parametrize(
    "text",
    [
        "Check status Anh Duong Core health/ready and database quick_check. Read only, no changes.",
        "Check status Anh Duong Core health/ready and DB quick_check. Read only, no changes.",
        "Check status Anh Duong Core health/ready and PRAGMA quick_check. Read only, no changes.",
    ],
)
def test_database_quick_check_aliases_are_detected(text: str) -> None:
    from app.safety_intent import requests_database_quick_check

    assert requests_database_quick_check(analyze_safety_intent(text)) is True


@pytest.mark.parametrize(
    "text",
    [
        (
            "Check status Anh Duong Core health/ready rotate credentials read only "
            "no changes no restart."
        ),
        (
            "Check status Anh Duong Core health/ready. Read only, no changes, "
            "no restart run malware."
        ),
    ],
)
def test_same_clause_unknown_action_fails_closed(text: str) -> None:
    from app.safety_intent import is_read_only_core_status_intent

    intent = analyze_safety_intent(text)
    assert intent.unnegated_mutation is True
    assert is_read_only_core_status_intent(intent) is False


def test_negated_readonly_marker_is_not_a_readonly_boundary() -> None:
    intent = analyze_safety_intent(
        "Không chỉ đọc. Kiểm tra trạng thái Ánh Dương Core health/ready, "
        "không thay đổi gì, không restart."
    )
    assert SafetyConstraint.READ_ONLY not in intent.constraints


def test_cpu_core_is_not_anh_duong_core_identity() -> None:
    from app.safety_intent import is_read_only_core_status_intent

    intent = analyze_safety_intent(
        "Check status of CPU core health/ready. Read only, no changes and no restart."
    )
    assert is_read_only_core_status_intent(intent) is False


@pytest.mark.parametrize(
    "text",
    [
        (
            "Check status Anh Duong Core health/ready. Read only, no changes and no restart. "
            "Report results by rotating credentials."
        ),
        (
            "Check status Anh Duong Core health/ready. Read only, no changes and no restart. "
            "Inspect rotating credentials."
        ),
        (
            "Check status Anh Duong Core health/ready. Read only, no changes and no restart. "
            "Tell me the result by wiping secrets."
        ),
    ],
)
def test_safe_prefix_never_hides_status_side_effect(text: str) -> None:
    from app.safety_intent import is_read_only_core_status_intent

    intent = analyze_safety_intent(text)
    assert intent.unnegated_mutation is True
    assert is_read_only_core_status_intent(intent) is False


@pytest.mark.parametrize(
    "suffix",
    [
        "deploy2 prod3.",
        "rotate2 credentials3.",
        "format1 disk2.",
        "AD1 deploy2 prod3.",
        "DR1deploy2.",
    ],
)
def test_numeric_looking_action_is_not_treated_as_safe_identifier(suffix: str) -> None:
    from app.safety_intent import is_read_only_core_status_intent

    text = (
        "Check status Anh Duong Core health/ready. Read only, no changes and no restart. " + suffix
    )
    intent = analyze_safety_intent(text)
    assert intent.unnegated_mutation is True
    assert is_read_only_core_status_intent(intent) is False


@pytest.mark.parametrize(
    "suffix",
    [
        "Report continue work.",
        "Báo kết quả khi tiếp tục làm việc.",
        "Báo thành công khi tiếp tục làm việc.",
    ],
)
def test_ambiguous_report_action_fails_closed(suffix: str) -> None:
    from app.safety_intent import is_read_only_core_status_intent

    text = (
        "Check status Anh Duong Core health/ready. Read only, no changes and no restart. " + suffix
    )
    intent = analyze_safety_intent(text)
    assert intent.unnegated_mutation is True
    assert is_read_only_core_status_intent(intent) is False


def test_exact_report_prefix_does_not_hide_appended_unknown_action() -> None:
    from app.safety_intent import is_read_only_core_status_intent

    text = (
        "Check status Anh Duong Core health/ready. Read only, no changes and no restart. "
        "Conclusion whether can continue working rotate credentials."
    )
    intent = analyze_safety_intent(text)
    assert intent.unnegated_mutation is True
    assert is_read_only_core_status_intent(intent) is False


def test_make_no_changes_is_safe_readonly_negation() -> None:
    from app.safety_intent import is_read_only_core_status_intent

    text = (
        "Check status Anh Duong Core health/ready. Read only and make no changes. "
        "Do not restart service."
    )
    intent = analyze_safety_intent(text)
    assert intent.unnegated_mutation is False
    assert is_read_only_core_status_intent(intent) is True


@pytest.mark.parametrize(
    "text",
    [
        (
            "Read only. No commands, no file changes, no config changes, no restart. "
            "Inspect credentials by rotating them."
        ),
        (
            "Read only. No commands, no file changes, no config changes, no restart. "
            "Inspect secrets by wiping them."
        ),
    ],
)
def test_nonstatus_observation_clause_never_hides_unknown_action(text: str) -> None:
    intent = analyze_safety_intent(text)
    assert intent.unnegated_mutation is True


def test_do_not_make_changes_is_safe_negation() -> None:
    from app.safety_intent import is_read_only_core_status_intent

    text = (
        "Check status Anh Duong Core health/ready. Read only, "
        "do not make changes and do not restart service."
    )
    intent = analyze_safety_intent(text)
    assert intent.unnegated_mutation is False
    assert is_read_only_core_status_intent(intent) is True


def test_shared_negation_survives_slash_separated_targets() -> None:
    from app.safety_intent import is_read_only_core_status_intent

    text = (
        "Check status Anh Duong Core health/ready. Read-only; "
        "no file/config changes; no service restart."
    )
    intent = analyze_safety_intent(text)
    assert intent.unnegated_mutation is False
    assert is_read_only_core_status_intent(intent) is True


def test_read_only_boundary_alone_is_not_observation_language() -> None:
    from app.safety_intent import is_read_only_core_status_intent

    intent = analyze_safety_intent(
        "Draft checklist status Anh Duong Core health ready. Read only, no changes and no restart."
    )

    assert intent.unnegated_mutation is False
    assert is_read_only_core_status_intent(intent) is False


@pytest.mark.parametrize(
    "text",
    [
        (
            "Soạn checklist kiểm tra trạng thái Ánh Dương Core health ready. "
            "Chỉ đọc, không thay đổi gì, không restart service."
        ),
        (
            "Draft checklist check status Anh Duong Core health ready. "
            "Read only, no changes, no restart service."
        ),
        (
            "Check status Anh Duong Core health ready, then draft checklist of results. "
            "Read only, no changes, no restart service."
        ),
        (
            "Check status Anh Duong Core health ready, then draft checklist. "
            "Read only, no changes, no restart service."
        ),
        (
            "Kiểm tra trạng thái Ánh Dương Core health ready, sau đó soạn checklist. "
            "Chỉ đọc, không thay đổi gì, không restart service."
        ),
    ],
)
def test_draft_checklist_never_becomes_live_status_execution(text: str) -> None:
    from app.safety_intent import is_read_only_core_status_intent, is_read_only_status_intent

    intent = analyze_safety_intent(text)

    assert is_read_only_status_intent(intent) is False
    assert is_read_only_core_status_intent(intent) is False


@pytest.mark.parametrize("suffix", ["deploy", "update", "publish"])
def test_ambiguous_no_changes_or_side_effect_fails_closed(suffix: str) -> None:
    from app.safety_intent import is_read_only_core_status_intent

    text = (
        "Check status Anh Duong Core health ready. "
        f"Read only, no changes or {suffix}. No restart service."
    )
    intent = analyze_safety_intent(text)
    assert intent.unnegated_mutation is True
    assert is_read_only_core_status_intent(intent) is False


@pytest.mark.parametrize(
    "suffix",
    [
        "Draft checklist deploy2 prod3.",
        "Report deploy2 prod3.",
    ],
)
def test_readonly_scaffold_or_report_prefix_never_hides_unknown_numeric_action(
    suffix: str,
) -> None:
    text = "Read only, no commands, no file changes, no config changes, no restart. " + suffix

    intent = analyze_safety_intent(text)

    assert intent.unnegated_mutation is True
