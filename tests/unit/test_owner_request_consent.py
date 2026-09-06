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


def test_owner_sensitive_requested_action_keeps_boundaries_without_second_gate():
    from app.async_tasks.models import AsyncTaskCreate
    from app.async_tasks.worker import AsyncTaskWorker
    from app.policy.models import PolicyDecision

    decision = PolicyDecision(
        kind="require_approval", effective_risk_level=2, rule_id="risk.sensitive", reason="test"
    )
    result = resolve(
        policy_engine=SimpleNamespace(evaluate=lambda action: decision),
        constraints=("no_paid_fallback",),
    )
    assert result.approval_required is False
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
    assert "no_unrequested_side_effects" in constraints
    assert constraints == result.constraints
