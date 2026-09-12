import hashlib
from types import SimpleNamespace

import pytest

from app.capabilities import CapabilityKind
from app.orchestration.models import CoreRequest
from app.orchestration.workflow import WorkflowResolver

OWNER = "123456789"
ACTOR = "telegram:" + hashlib.sha256(OWNER.encode()).hexdigest()


def resolve(
    actor=ACTOR,
    origin="telegram_user",
    message_id="11111111-1111-4111-8111-111111111111",
    owner=OWNER,
    policy_engine=None,
    constraints=(),
):
    resolver = WorkflowResolver(policy_engine, owner_telegram_id=owner)
    request = CoreRequest(
        text="Fix the application in the workspace",
        channel="telegram",
        actor=actor,
        source_chat_id=OWNER,
        source_session_id="agent:main:telegram:direct:" + OWNER,
        source_message_id=message_id,
    ).model_copy(update={"source_origin": origin})
    project = SimpleNamespace(
        id="proj_owner",
        path_wsl="/mnt/f/AIOS/project",
        constraints=constraints,
        priority=SimpleNamespace(value="normal"),
    )
    return resolver.resolve(
        request=request,
        request_id="owner-test",
        normalized_text=request.text,
        capability=CapabilityKind.CODE_OPERATION,
        project=project,
    )


def test_live_owner_request_does_not_require_second_approval():
    result = resolve()
    assert result.approval_required is False
    assert result.policy_rule_id == "owner.direct_request"
    assert "owner_request_authorized_current_goal" in result.constraints


def test_owner_harmless_bounded_shell_like_command_does_not_require_second_approval():
    result = WorkflowResolver(owner_telegram_id=OWNER).resolve(
        request=CoreRequest(
            text="Chạy lệnh sleep 5 && echo ACK-CLEANUP-E2E rồi báo kết quả, không làm gì khác.",
            channel="telegram",
            actor=ACTOR,
            source_chat_id=OWNER,
            source_session_id="agent:main:telegram:direct:" + OWNER,
            source_message_id="22222222-2222-4222-8222-222222222222",
        ).model_copy(update={"source_origin": "telegram_user"}),
        request_id="owner-harmless-shell",
        normalized_text=(
            "Chạy lệnh sleep 5 && echo ACK-CLEANUP-E2E rồi báo kết quả, không làm gì khác."
        ),
        capability=CapabilityKind.UNKNOWN_WORKFLOW,
        project=SimpleNamespace(
            id="proj_owner",
            path_wsl="/mnt/f/AIOS/project",
            constraints=(),
            priority=SimpleNamespace(value="normal"),
        ),
    )
    assert result.approval_required is False
    assert result.policy_rule_id == "owner.direct_request"


def test_owner_low_effect_normal_workflow_does_not_require_second_approval():
    result = WorkflowResolver(owner_telegram_id=OWNER).resolve(
        request=CoreRequest(
            text="Lập kế hoạch kiểm tra cục bộ rồi báo lại.",
            channel="telegram",
            actor=ACTOR,
            source_chat_id=OWNER,
            source_session_id="agent:main:telegram:direct:" + OWNER,
            source_message_id="33333333-3333-4333-8333-333333333333",
        ).model_copy(update={"source_origin": "telegram_user"}),
        request_id="owner-normal-workflow",
        normalized_text="Lập kế hoạch kiểm tra cục bộ rồi báo lại.",
        capability=CapabilityKind.PLANNING,
        project=SimpleNamespace(
            id="proj_owner",
            path_wsl="/mnt/f/AIOS/project",
            constraints=(),
            priority=SimpleNamespace(value="normal"),
        ),
    )
    assert result.approval_required is False
    assert result.policy_rule_id in {"risk.safe_write.allow", "owner.direct_request"}


@pytest.mark.parametrize(
    "kwargs",
    [
        {"actor": "telegram:anonymous"},
        {"actor": "telegram:" + "a" * 64},
        {"origin": "unknown"},
        {"origin": "cron"},
        {"message_id": "compat-generated"},
        {"owner": None},
    ],
)
def test_non_owner_or_synthetic_request_keeps_existing_gate(kwargs):
    assert resolve(**kwargs).approval_required is True


@pytest.mark.parametrize(
    "kind,risk,rule",
    [
        ("deny", 4, "security.forbidden"),
        ("deny", 2, "path.outside_roots"),
        ("escalate", 2, "policy.unresolved"),
        ("require_approval", 4, "risk.forbidden"),
    ],
)
def test_owner_consent_cannot_override_denial_or_forbidden_risk(kind, risk, rule):
    from app.policy.models import PolicyDecision

    decision = PolicyDecision(kind=kind, effective_risk_level=risk, rule_id=rule, reason="test")
    result = resolve(policy_engine=SimpleNamespace(evaluate=lambda action: decision))
    assert result.approval_required is True
    assert result.policy_rule_id == rule
    assert "owner_request_authorized_current_goal" not in result.constraints


def test_project_constraint_cannot_grant_owner_consent():
    result = resolve(
        actor="telegram:anonymous", constraints=("owner_request_authorized_current_goal",)
    )
    assert "owner_request_authorized_current_goal" not in result.constraints
    assert result.approval_required is True


def test_owner_sensitive_requested_action_requires_real_confirmation_gate():
    from app.async_tasks.models import AsyncTaskCreate
    from app.async_tasks.worker import AsyncTaskWorker
    from app.policy.models import PolicyDecision

    decision = PolicyDecision(
        kind="require_approval",
        effective_risk_level=2,
        rule_id="risk.sensitive",
        reason="test",
    )
    result = resolve(
        policy_engine=SimpleNamespace(evaluate=lambda action: decision),
        constraints=("no_paid_fallback",),
    )
    assert result.approval_required is True
    assert result.policy_rule_id == "risk.sensitive"
    request = AsyncTaskCreate(
        project_id=result.project_id,
        title=result.title,
        goal=result.goal,
        risk_level=result.risk_level,
        approval_required=result.approval_required,
        constraints=result.constraints,
    )
    constraints = AsyncTaskWorker._execution_constraints(request)
    assert "no_paid_fallback" in constraints
    assert "owner_request_authorized_current_goal" not in constraints
    assert "hard_gate_publish_send_external_destructive_secret_cost" in constraints


def test_owner_commit_requires_real_confirmation_gate():
    result = WorkflowResolver(owner_telegram_id=OWNER).resolve(
        request=CoreRequest(
            text="Commit thay đổi này",
            channel="telegram",
            actor=ACTOR,
            source_chat_id=OWNER,
            source_session_id="agent:main:telegram:direct:" + OWNER,
            source_message_id="44444444-4444-4444-8444-444444444444",
        ).model_copy(update={"source_origin": "telegram_user"}),
        request_id="owner-commit-gate",
        normalized_text="Commit thay đổi này",
        capability=CapabilityKind.SYSTEM_OPERATION,
        project=SimpleNamespace(
            id="proj_owner",
            path_wsl="/mnt/f/AIOS/project",
            constraints=(),
            priority=SimpleNamespace(value="normal"),
        ),
    )
    assert result.approval_required is True
    assert result.policy_rule_id == "risk.sensitive.require_approval"


@pytest.mark.parametrize(
    "text",
    [
        "Đổi quyền file này",
        "Gửi báo cáo này ra ngoài",
        "Thao tác này cần mật khẩu để tiếp tục",
    ],
)
def test_owner_privileged_or_external_side_effects_require_confirmation(text: str):
    result = WorkflowResolver(owner_telegram_id=OWNER).resolve(
        request=CoreRequest(
            text=text,
            channel="telegram",
            actor=ACTOR,
            source_chat_id=OWNER,
            source_session_id="agent:main:telegram:direct:" + OWNER,
            source_message_id="55555555-5555-4555-8555-555555555555",
        ).model_copy(update={"source_origin": "telegram_user"}),
        request_id="owner-real-gate-matrix",
        normalized_text=text,
        capability=CapabilityKind.SYSTEM_OPERATION,
        project=SimpleNamespace(
            id="proj_owner",
            path_wsl="/mnt/f/AIOS/project",
            constraints=(),
            priority=SimpleNamespace(value="normal"),
        ),
    )
    assert result.approval_required is True
    assert result.policy_rule_id in {
        "risk.high.require_explicit_approval",
        "risk.sensitive.require_approval",
    }


def test_owner_negated_password_requirement_does_not_create_confirmation_gate():
    text = "Thao tác này không cần mật khẩu để tiếp tục"
    result = WorkflowResolver(owner_telegram_id=OWNER).resolve(
        request=CoreRequest(
            text=text,
            channel="telegram",
            actor=ACTOR,
            source_chat_id=OWNER,
            source_session_id="agent:main:telegram:direct:" + OWNER,
            source_message_id="66666666-6666-4666-8666-666666666666",
        ).model_copy(update={"source_origin": "telegram_user"}),
        request_id="owner-negated-password-gate",
        normalized_text=text,
        capability=CapabilityKind.SYSTEM_OPERATION,
        project=SimpleNamespace(
            id="proj_owner",
            path_wsl="/mnt/f/AIOS/project",
            constraints=(),
            priority=SimpleNamespace(value="normal"),
        ),
    )
    assert result.approval_required is False
    assert result.policy_rule_id == "owner.direct_request"


@pytest.mark.parametrize(
    "text",
    [
        "Không deploy. Chỉ sửa file config.",
        "Không restart service. Chạy test đi.",
        "Không dùng sudo. Chạy test thôi.",
        "Không gửi ra ngoài. Chỉ lưu file.",
        "Do not change permissions. Run tests only.",
        "Do not send externally. Save the report locally.",
        "No password required for this step. Run tests only.",
    ],
)
def test_owner_negated_gated_effects_do_not_create_confirmation_gate(text: str):
    result = WorkflowResolver(owner_telegram_id=OWNER).resolve(
        request=CoreRequest(
            text=text,
            channel="telegram",
            actor=ACTOR,
            source_chat_id=OWNER,
            source_session_id="agent:main:telegram:direct:" + OWNER,
            source_message_id="77777777-7777-4777-8777-777777777777",
        ).model_copy(update={"source_origin": "telegram_user"}),
        request_id="owner-negated-gate-matrix",
        normalized_text=text,
        capability=CapabilityKind.CODE_OPERATION,
        project=SimpleNamespace(
            id="proj_owner",
            path_wsl="/mnt/f/AIOS/project",
            constraints=(),
            priority=SimpleNamespace(value="normal"),
        ),
    )
    assert result.approval_required is False
    assert result.policy_rule_id == "owner.direct_request"

@pytest.mark.parametrize(
    "text",
    [
        "Không disable audit. Chỉ chạy test đi.",
        "Do not bypass auth. Run tests only.",
    ],
)
def test_owner_negated_forbidden_effect_is_not_treated_as_requested_action(text: str):
    result = WorkflowResolver(owner_telegram_id=OWNER).resolve(
        request=CoreRequest(
            text=text,
            channel="telegram",
            actor=ACTOR,
            source_chat_id=OWNER,
            source_session_id="agent:main:telegram:direct:" + OWNER,
            source_message_id="88888888-8888-4888-8888-888888888888",
        ).model_copy(update={"source_origin": "telegram_user"}),
        request_id="owner-negated-forbidden",
        normalized_text=text,
        capability=CapabilityKind.CODE_OPERATION,
        project=SimpleNamespace(
            id="proj_owner",
            path_wsl="/mnt/f/AIOS/project",
            constraints=(),
            priority=SimpleNamespace(value="normal"),
        ),
    )
    assert result.approval_required is False
    assert result.policy_rule_id == "owner.direct_request"


@pytest.mark.parametrize("text", ["Disable audit đi.", "Bypass auth rồi chạy tiếp."])
def test_owner_positive_forbidden_effect_remains_denied(text: str):
    result = WorkflowResolver(owner_telegram_id=OWNER).resolve(
        request=CoreRequest(
            text=text,
            channel="telegram",
            actor=ACTOR,
            source_chat_id=OWNER,
            source_session_id="agent:main:telegram:direct:" + OWNER,
            source_message_id="99999999-9999-4999-8999-999999999999",
        ).model_copy(update={"source_origin": "telegram_user"}),
        request_id="owner-positive-forbidden",
        normalized_text=text,
        capability=CapabilityKind.CODE_OPERATION,
        project=SimpleNamespace(
            id="proj_owner",
            path_wsl="/mnt/f/AIOS/project",
            constraints=(),
            priority=SimpleNamespace(value="normal"),
        ),
    )
    assert result.approval_required is True
    assert result.policy_rule_id == "risk.forbidden.deny"
