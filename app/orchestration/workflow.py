from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.capabilities import CapabilityKind
from app.orchestration.errors import WorkflowPreparationFailed
from app.orchestration.models import CoreRequest, WorkflowEnvelope
from app.policy import DecisionKind, PolicyAction, PolicyEngine, RiskLevel
from app.privacy import telegram_idempotency_key
from app.projects import Project
from app.safety_intent import SafetyConstraint, analyze_safety_intent

_OPERATIONAL_GUIDANCE_MARKERS = (
    "hướng dẫn",
    "cách",
    "thế nào",
    "như nào",
    "cho anh lệnh",
    "cho tôi lệnh",
    "nói anh cách",
    "nói tôi cách",
    "ở đâu",
    "how to",
    "guide me",
    "tell me how",
    "where is",
    "which command",
    "what command",
)


class WorkflowResolver:
    """Build an async envelope without delegating policy to OpenClaw."""

    def __init__(self, policy_engine: PolicyEngine | None = None) -> None:
        self._policy_engine = policy_engine or PolicyEngine.with_default_roots()

    def resolve(
        self,
        *,
        request: CoreRequest,
        request_id: str,
        normalized_text: str,
        capability: CapabilityKind,
        project: Project,
    ) -> WorkflowEnvelope:
        if request.channel == "telegram" and not all(
            (
                request.source_chat_id,
                request.source_session_id,
                request.source_message_id,
            )
        ):
            raise WorkflowPreparationFailed(
                "Telegram workflow requires chat, session, and message identity."
            )

        action_name, declared_risk, safety_constraints = self._action(
            normalized_text,
            capability,
        )
        decision = self._policy_engine.evaluate(
            PolicyAction(
                name=action_name,
                declared_risk_level=declared_risk,
                workspace_root=(
                    Path(project.path_wsl)
                    if project.path_wsl is not None
                    else None
                ),
            )
        )
        constraints = tuple(
            self._stringify(item) for item in project.constraints
        ) + safety_constraints
        return WorkflowEnvelope(
            project_id=project.id,
            title=normalized_text[:255],
            goal=normalized_text,
            mode=(
                "quick"
                if decision.effective_risk_level is RiskLevel.READ_ONLY
                else "build"
            ),
            priority=project.priority.value,
            risk_level=decision.effective_risk_level,
            approval_required=decision.kind is not DecisionKind.ALLOW,
            workspace=project.path_wsl,
            requested_by=request.actor,
            source_channel=request.channel,
            source_chat_id=request.source_chat_id,
            source_session_id=request.source_session_id,
            source_message_id=request.source_message_id,
            idempotency_key=self._idempotency_key(request),
            correlation_id=request_id,
            constraints=constraints,
            policy_decision=decision.kind,
            policy_rule_id=decision.rule_id,
            policy_reason=decision.reason,
        )

    @staticmethod
    def _action(
        text: str,
        capability: CapabilityKind,
    ) -> tuple[str, RiskLevel | None, tuple[str, ...]]:
        safety = analyze_safety_intent(text)
        folded = text.casefold()
        normalized = safety.normalized_text
        has_read_only_status_check = (
            safety.has(SafetyConstraint.READ_ONLY)
            and "kiem tra" in normalized
            and "trang thai" in normalized
            and "health" in normalized
            and "ready" in normalized
            and safety.has(SafetyConstraint.NO_FILE_CHANGES)
            and safety.has(SafetyConstraint.NO_CONFIG_CHANGES)
            and safety.has(SafetyConstraint.NO_SERVICE_RESTART)
        )
        has_operational_guidance = (
            capability is CapabilityKind.SYSTEM_OPERATION
            and any(
                marker in folded
                for marker in _OPERATIONAL_GUIDANCE_MARKERS
            )
        )
        if capability is CapabilityKind.VISUAL_PROMPT_COMPOSE:
            return (
                "compose_visual_prompt",
                RiskLevel.READ_ONLY,
                (
                    "read_only",
                    "no_external_network",
                    "no_file_changes",
                    "no_config_changes",
                    "no_service_restart",
                    "no_system_mutation",
                ),
            )
        if has_operational_guidance:
            return (
                "view_status",
                RiskLevel.READ_ONLY,
                (
                    "read_only",
                    "verify_runtime_before_guidance",
                    "no_unverified_operational_commands",
                    "no_file_changes",
                    "no_config_changes",
                    "no_service_restart",
                    "no_package_install",
                    "no_deploy",
                ),
            )
        if has_read_only_status_check:
            constraints = tuple(
                dict.fromkeys(
                    (
                        SafetyConstraint.READ_ONLY.value,
                        SafetyConstraint.NO_FILE_CHANGES.value,
                        SafetyConstraint.NO_CONFIG_CHANGES.value,
                        SafetyConstraint.NO_SERVICE_RESTART.value,
                        SafetyConstraint.NO_PACKAGE_INSTALL.value,
                        SafetyConstraint.NO_DEPLOY.value,
                        *safety.values(),
                    )
                )
            )
            return "view_status", RiskLevel.READ_ONLY, constraints

        has_legacy_read_only_boundaries = all(
            safety.has(constraint)
            for constraint in (
                SafetyConstraint.READ_ONLY,
                SafetyConstraint.NO_COMMANDS,
                SafetyConstraint.NO_FILE_CHANGES,
                SafetyConstraint.NO_CONFIG_CHANGES,
                SafetyConstraint.NO_SERVICE_RESTART,
            )
        )
        has_bounded_no_side_effect = (
            safety.has(SafetyConstraint.READ_ONLY)
            and safety.has(SafetyConstraint.NO_FILE_CHANGES)
            and safety.has(SafetyConstraint.NO_SYSTEM_MUTATION)
        )
        if has_legacy_read_only_boundaries or has_bounded_no_side_effect:
            constraints = tuple(
                dict.fromkeys(
                    (
                        SafetyConstraint.READ_ONLY.value,
                        SafetyConstraint.NO_COMMANDS.value,
                        SafetyConstraint.NO_FILE_CHANGES.value,
                        SafetyConstraint.NO_CONFIG_CHANGES.value,
                        SafetyConstraint.NO_SERVICE_RESTART.value,
                        *safety.values(),
                    )
                )
            )
            return "view_status", RiskLevel.READ_ONLY, constraints
        if capability is CapabilityKind.PLANNING:
            return "create_plan", RiskLevel.SAFE_WRITE, ()
        return f"workflow_{capability.value}", None, ()

    @staticmethod
    def _idempotency_key(request: CoreRequest) -> str | None:
        if request.channel != "telegram":
            return None
        if not request.source_chat_id or not request.source_message_id:
            return None
        return telegram_idempotency_key(
            source_chat_id=request.source_chat_id,
            source_message_id=request.source_message_id,
        )

    @staticmethod
    def _stringify(value: Any) -> str:
        if isinstance(value, str):
            return value
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
