from pathlib import Path

from app.policy.engine import PolicyEngine
from app.policy.models import (
    ApprovalScope,
    DecisionKind,
    PolicyAction,
    RiskLevel,
)
from app.policy.path_scope import WorkspacePathPolicy


def _engine(allowed_root: Path) -> PolicyEngine:
    return PolicyEngine(
        path_policy=WorkspacePathPolicy((allowed_root,)),
    )


def test_read_only_status_action_is_allowed(tmp_path: Path) -> None:
    decision = _engine(tmp_path).evaluate(
        PolicyAction(name="view_status")
    )

    assert decision.kind is DecisionKind.ALLOW
    assert decision.effective_risk_level is RiskLevel.READ_ONLY
    assert decision.rule_id == "risk.read_only.allow"


def test_read_file_inside_allowed_workspace_is_allowed(
    tmp_path: Path,
) -> None:
    target = tmp_path / "project" / "README.md"

    decision = _engine(tmp_path).evaluate(
        PolicyAction(name="read_file", target_path=target)
    )

    assert decision.kind is DecisionKind.ALLOW
    assert decision.normalized_target_path == target.resolve(strict=False)


def test_safe_write_inside_allowed_workspace_is_allowed(
    tmp_path: Path,
) -> None:
    target = tmp_path / "project" / "new.md"

    decision = _engine(tmp_path).evaluate(
        PolicyAction(name="create_file", target_path=target)
    )

    assert decision.kind is DecisionKind.ALLOW
    assert decision.effective_risk_level is RiskLevel.SAFE_WRITE


def test_safe_write_without_target_path_is_escalated(
    tmp_path: Path,
) -> None:
    decision = _engine(tmp_path).evaluate(
        PolicyAction(name="create_file")
    )

    assert decision.kind is DecisionKind.ESCALATE
    assert decision.rule_id == "path.required"


def test_sensitive_action_requires_single_action_approval(
    tmp_path: Path,
) -> None:
    decision = _engine(tmp_path).evaluate(
        PolicyAction(name="restart_service")
    )

    assert decision.kind is DecisionKind.REQUIRE_APPROVAL
    assert decision.effective_risk_level is RiskLevel.SENSITIVE
    assert decision.approval_scope is ApprovalScope.SINGLE_ACTION


def test_high_risk_action_requires_explicit_approval(
    tmp_path: Path,
) -> None:
    decision = _engine(tmp_path).evaluate(
        PolicyAction(name="deploy")
    )

    assert decision.kind is DecisionKind.REQUIRE_APPROVAL
    assert decision.effective_risk_level is RiskLevel.HIGH_RISK
    assert decision.rule_id == "risk.high.require_explicit_approval"


def test_forbidden_action_is_denied_even_when_declared_low_risk(
    tmp_path: Path,
) -> None:
    decision = _engine(tmp_path).evaluate(
        PolicyAction(
            name="disable_audit",
            declared_risk_level=RiskLevel.READ_ONLY,
        )
    )

    assert decision.kind is DecisionKind.DENY
    assert decision.effective_risk_level is RiskLevel.FORBIDDEN


def test_unknown_action_is_escalated(tmp_path: Path) -> None:
    decision = _engine(tmp_path).evaluate(
        PolicyAction(name="new_unregistered_skill")
    )

    assert decision.kind is DecisionKind.ESCALATE
    assert decision.rule_id == "action.unknown"


def test_cost_flag_upgrades_known_safe_action_to_high_risk(
    tmp_path: Path,
) -> None:
    decision = _engine(tmp_path).evaluate(
        PolicyAction(name="view_status", incurs_cost=True)
    )

    assert decision.kind is DecisionKind.REQUIRE_APPROVAL
    assert decision.effective_risk_level is RiskLevel.HIGH_RISK


def test_safety_bypass_flag_forces_deny(tmp_path: Path) -> None:
    decision = _engine(tmp_path).evaluate(
        PolicyAction(name="view_status", bypasses_security=True)
    )

    assert decision.kind is DecisionKind.DENY
    assert decision.effective_risk_level is RiskLevel.FORBIDDEN


def test_higher_declared_risk_is_never_downgraded(
    tmp_path: Path,
) -> None:
    decision = _engine(tmp_path).evaluate(
        PolicyAction(
            name="view_status",
            declared_risk_level=RiskLevel.HIGH_RISK,
        )
    )

    assert decision.kind is DecisionKind.REQUIRE_APPROVAL
    assert decision.effective_risk_level is RiskLevel.HIGH_RISK


def test_forbidden_flag_on_unknown_action_is_denied(
    tmp_path: Path,
) -> None:
    decision = _engine(tmp_path).evaluate(
        PolicyAction(
            name="unknown_action",
            requests_privilege_escalation=True,
        )
    )

    assert decision.kind is DecisionKind.DENY
    assert decision.rule_id == "risk.forbidden.deny"
