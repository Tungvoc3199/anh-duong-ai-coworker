from __future__ import annotations

from pathlib import Path

from app.policy.models import (
    ApprovalScope,
    DecisionKind,
    PolicyAction,
    PolicyDecision,
    RiskLevel,
)
from app.policy.path_scope import WorkspacePathPolicy

POLICY_VERSION = "1.0"

ACTION_RISK_CATALOG: dict[str, RiskLevel] = {
    "read_file": RiskLevel.READ_ONLY,
    "read_log": RiskLevel.READ_ONLY,
    "view_status": RiskLevel.READ_ONLY,
    "summarize_document": RiskLevel.READ_ONLY,
    "analyze_repository": RiskLevel.READ_ONLY,
    "search_memory": RiskLevel.READ_ONLY,
    "create_file": RiskLevel.SAFE_WRITE,
    "edit_file_with_backup": RiskLevel.SAFE_WRITE,
    "create_plan": RiskLevel.SAFE_WRITE,
    "create_draft": RiskLevel.SAFE_WRITE,
    "run_tests": RiskLevel.SAFE_WRITE,
    "create_local_branch": RiskLevel.SAFE_WRITE,
    "restart_service": RiskLevel.SENSITIVE,
    "modify_runtime_config": RiskLevel.SENSITIVE,
    "install_package": RiskLevel.SENSITIVE,
    "overwrite_critical_file": RiskLevel.SENSITIVE,
    "alter_database_schema": RiskLevel.SENSITIVE,
    "quota_api_call": RiskLevel.SENSITIVE,
    "delete_data": RiskLevel.HIGH_RISK,
    "push_git": RiskLevel.HIGH_RISK,
    "merge_git": RiskLevel.HIGH_RISK,
    "deploy": RiskLevel.HIGH_RISK,
    "publish": RiskLevel.HIGH_RISK,
    "send_email": RiskLevel.HIGH_RISK,
    "send_external_data": RiskLevel.HIGH_RISK,
    "incur_cost": RiskLevel.HIGH_RISK,
    "change_permissions": RiskLevel.HIGH_RISK,
    "bypass_auth": RiskLevel.FORBIDDEN,
    "disable_audit": RiskLevel.FORBIDDEN,
    "self_approve": RiskLevel.FORBIDDEN,
    "exfiltrate_secret": RiskLevel.FORBIDDEN,
    "elevate_privileges": RiskLevel.FORBIDDEN,
    "arbitrary_shell": RiskLevel.FORBIDDEN,
}

PATH_REQUIRED_ACTIONS = frozenset(
    {
        "read_file",
        "read_log",
        "summarize_document",
        "analyze_repository",
        "create_file",
        "edit_file_with_backup",
        "run_tests",
        "create_local_branch",
        "overwrite_critical_file",
        "delete_data",
    }
)


class PolicyEngine:
    """Pure rules: no LLM, network, database, or shell calls."""

    def __init__(self, path_policy: WorkspacePathPolicy) -> None:
        self.path_policy = path_policy

    @classmethod
    def with_default_roots(cls) -> PolicyEngine:
        return cls(
            WorkspacePathPolicy(
                (
                    Path("/mnt/f/AIOS"),
                    Path("/mnt/f/SecondBrain_AI"),
                )
            )
        )

    def evaluate(self, action: PolicyAction) -> PolicyDecision:
        flag_risk = self._flag_risk(action)
        catalog_risk = ACTION_RISK_CATALOG.get(action.name)

        if (
            flag_risk is RiskLevel.FORBIDDEN
            or catalog_risk is RiskLevel.FORBIDDEN
            or action.declared_risk_level is RiskLevel.FORBIDDEN
        ):
            return PolicyDecision(
                kind=DecisionKind.DENY,
                effective_risk_level=RiskLevel.FORBIDDEN,
                rule_id="risk.forbidden.deny",
                reason=(
                    "Forbidden actions cannot be approved or executed."
                ),
            )

        if catalog_risk is None:
            declared_risk = (
                action.declared_risk_level
                or RiskLevel.READ_ONLY
            )
            return PolicyDecision(
                kind=DecisionKind.ESCALATE,
                effective_risk_level=max(
                    declared_risk,
                    flag_risk,
                ),
                rule_id="action.unknown",
                reason=(
                    f"Action '{action.name}' is not registered in "
                    f"Policy catalog v{POLICY_VERSION}."
                ),
            )

        effective_risk = max(
            catalog_risk,
            action.declared_risk_level or RiskLevel.READ_ONLY,
            flag_risk,
        )

        path_decision, normalized_target = self._evaluate_path(
            action,
            catalog_risk,
        )
        if path_decision is not None:
            return path_decision

        if effective_risk is RiskLevel.HIGH_RISK:
            return PolicyDecision(
                kind=DecisionKind.REQUIRE_APPROVAL,
                effective_risk_level=effective_risk,
                rule_id="risk.high.require_explicit_approval",
                reason=(
                    "High-risk action requires explicit, one-time "
                    "user approval."
                ),
                approval_scope=ApprovalScope.SINGLE_ACTION,
                normalized_target_path=normalized_target,
            )

        if effective_risk is RiskLevel.SENSITIVE:
            return PolicyDecision(
                kind=DecisionKind.REQUIRE_APPROVAL,
                effective_risk_level=effective_risk,
                rule_id="risk.sensitive.require_approval",
                reason=(
                    "Sensitive action requires one-time user approval."
                ),
                approval_scope=ApprovalScope.SINGLE_ACTION,
                normalized_target_path=normalized_target,
            )

        if effective_risk is RiskLevel.SAFE_WRITE:
            return PolicyDecision(
                kind=DecisionKind.ALLOW,
                effective_risk_level=effective_risk,
                rule_id="risk.safe_write.allow",
                reason=(
                    "Safe write is allowed inside the approved "
                    "workspace."
                ),
                normalized_target_path=normalized_target,
            )

        return PolicyDecision(
            kind=DecisionKind.ALLOW,
            effective_risk_level=RiskLevel.READ_ONLY,
            rule_id="risk.read_only.allow",
            reason="Read-only action is allowed by policy.",
            normalized_target_path=normalized_target,
        )

    def _evaluate_path(
        self,
        action: PolicyAction,
        catalog_risk: RiskLevel,
    ) -> tuple[PolicyDecision | None, Path | None]:
        if (
            action.name in PATH_REQUIRED_ACTIONS
            and action.target_path is None
        ):
            return (
                PolicyDecision(
                    kind=DecisionKind.ESCALATE,
                    effective_risk_level=catalog_risk,
                    rule_id="path.required",
                    reason=(
                        f"Action '{action.name}' requires a target "
                        "path before policy can decide."
                    ),
                ),
                None,
            )

        if action.target_path is None:
            return None, None

        result = self.path_policy.check(
            action.target_path,
            workspace_root=action.workspace_root,
        )
        if not result.allowed:
            return (
                PolicyDecision(
                    kind=DecisionKind.DENY,
                    effective_risk_level=RiskLevel.FORBIDDEN,
                    rule_id=result.rule_id,
                    reason=result.reason,
                    normalized_target_path=result.normalized_path,
                ),
                result.normalized_path,
            )

        return None, result.normalized_path

    @staticmethod
    def _flag_risk(action: PolicyAction) -> RiskLevel:
        if any(
            (
                action.bypasses_security,
                action.disables_audit,
                action.requests_self_approval,
                action.requests_privilege_escalation,
                action.exposes_secrets,
            )
        ):
            return RiskLevel.FORBIDDEN

        if any(
            (
                action.destructive,
                action.external_side_effect,
                action.sends_data_externally,
                action.incurs_cost,
                action.changes_permissions,
                action.deploys_or_publishes,
            )
        ):
            return RiskLevel.HIGH_RISK

        if any(
            (
                action.modifies_runtime,
                action.installs_dependencies,
                action.changes_schema,
                action.uses_quota,
            )
        ):
            return RiskLevel.SENSITIVE

        return RiskLevel.READ_ONLY
