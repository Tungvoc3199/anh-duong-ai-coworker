from app.orchestration.contextual_referent import (
    depends_on_contextual_referent,
    requests_contextual_execution,
    resolve_contextual_referent,
    semantic_text,
)
from app.orchestration.models import ContextualReferent


def _ref(text: str = "Deploy bản fix đã kiểm thử.") -> ContextualReferent:
    return ContextualReferent(
        source="quoted_message",
        message_id="5963",
        text=text,
        sender="Ánh Dương",
    )


def test_requested_natural_followups_are_context_dependent() -> None:
    for text in (
        "sửa lỗi đó",
        "làm theo cái em vừa nói",
        "cái trên",
        "ảnh này",
        "giữ phần còn lại",
        "phương án 2",
        "làm như trên",
    ):
        assert depends_on_contextual_referent(text) is True


def test_hom_nay_does_not_false_bind_replied_context() -> None:
    assert depends_on_contextual_referent("Hôm nay có gì mới?") is False
    assert semantic_text("Hôm nay có gì mới?", _ref()) == "Hôm nay có gì mới?"


def test_resolved_semantic_text_keeps_current_instruction_first_and_marks_reference_data() -> None:
    resolved = semantic_text("Làm theo cái em vừa nói.", _ref("Deploy bản fix đã kiểm thử."))
    assert resolved.startswith("Làm theo cái em vừa nói.")
    assert "[CONTEXTUAL_REFERENCE_DATA]" in resolved
    assert resolved.endswith("Deploy bản fix đã kiểm thử.")


def test_explicit_quote_wins_over_recent_assistant_candidate() -> None:
    explicit = _ref("Explicit quote.")
    recent = ContextualReferent(
        source="previous_assistant_result",
        message_id="5962",
        text="Recent assistant result.",
        sender="Ánh Dương",
    )
    assert resolve_contextual_referent("Hôm nay có gì mới?", explicit, recent) == explicit


def test_recent_assistant_candidate_is_used_only_for_context_dependent_followup() -> None:
    recent = ContextualReferent(
        source="previous_assistant_result",
        message_id="5962",
        text="Phương án 1: A. Phương án 2: B.",
        sender="Ánh Dương",
    )
    assert resolve_contextual_referent("Phương án 2.", None, recent) == recent
    assert resolve_contextual_referent("Hôm nay có gì mới?", None, recent) is None


def test_only_explicit_contextual_delegation_inherits_reference_actions() -> None:
    assert requests_contextual_execution("Làm theo cái em vừa nói.") is True
    assert requests_contextual_execution("Cái trên có nguy hiểm không?") is False
