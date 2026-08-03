from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from app.capabilities import CapabilityKind
from app.orchestration.errors import WorkflowPreparationFailed
from app.orchestration.models import CoreRequest, WorkflowEnvelope
from app.policy import DecisionKind, PolicyAction, PolicyEngine, RiskLevel
from app.projects import Project

_READ_ONLY_MARKERS = (
    "chỉ đọc",
    "không chạy lệnh",
    "không sửa file",
    "không sửa cấu hình",
)

_NO_SIDE_EFFECT_MARKERS = (
    "không thực hiện side effect",
    "no side effect",
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
        folded = text.casefold()
        has_no_restart = (
            "không restart" in folded
            or "không khởi động lại" in folded
        )
        has_no_side_effect = any(
            marker in folded for marker in _NO_SIDE_EFFECT_MARKERS
        )
        has_legacy_read_only_boundaries = all(
            marker in folded for marker in _READ_ONLY_MARKERS
        )
        has_bounded_no_side_effect = (
            "chỉ đọc" in folded
            and "không sửa file" in folded
            and has_no_side_effect
        )
        if (
            has_legacy_read_only_boundaries and has_no_restart
        ) or has_bounded_no_side_effect:
            return (
                "view_status",
                RiskLevel.READ_ONLY,
                (
                    "read_only",
                    "no_commands",
                    "no_file_changes",
                    "no_config_changes",
                    "no_service_restart",
                ),
            )
        if capability is CapabilityKind.PLANNING:
            return "create_plan", RiskLevel.SAFE_WRITE, ()
        return f"workflow_{capability.value}", None, ()

    @staticmethod
    def _idempotency_key(request: CoreRequest) -> str | None:
        if request.channel != "telegram":
            return None
        if not request.source_chat_id or not request.source_message_id:
            return None
        candidate = (
            f"telegram:{request.source_chat_id}:{request.source_message_id}"
        )
        if len(candidate) <= 255:
            return candidate
        return "telegram:" + hashlib.sha256(candidate.encode("utf-8")).hexdigest()

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
