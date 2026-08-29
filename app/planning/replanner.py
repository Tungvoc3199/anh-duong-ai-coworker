from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from app.planning.models import (
    Constraint,
    Plan,
    PlanningTruthSnapshot,
    PlanStatus,
)


class ReplanDisposition(StrEnum):
    KEEP = "keep"
    REVISED = "revised"
    BLOCKED = "blocked"


class ReplanDecision(BaseModel):
    model_config = ConfigDict(frozen=True)

    disposition: ReplanDisposition
    plan: Plan
    reason: str


class PlanReplanner:
    _EXECUTABLE_STATUSES = frozenset({"active"})

    def reconcile(
        self,
        plan: Plan,
        fresh_truth: PlanningTruthSnapshot,
        *,
        execution_started: bool,
    ) -> ReplanDecision:
        if plan.status is PlanStatus.BLOCKED:
            return ReplanDecision(
                disposition=ReplanDisposition.BLOCKED,
                plan=plan,
                reason="Plan is already blocked.",
            )
        if fresh_truth.project_id != plan.truth.project_id:
            return ReplanDecision(
                disposition=ReplanDisposition.BLOCKED,
                plan=plan,
                reason="Planning truth project identity changed.",
            )
        if fresh_truth.project_status not in self._EXECUTABLE_STATUSES:
            return ReplanDecision(
                disposition=ReplanDisposition.BLOCKED,
                plan=plan,
                reason=(
                    "Project status is not executable: "
                    f"{fresh_truth.project_status}."
                ),
            )
        workspace_planned = (
            plan.truth.workspace is not None or fresh_truth.workspace is not None
        )
        if workspace_planned and not fresh_truth.workspace_exists:
            return ReplanDecision(
                disposition=ReplanDisposition.BLOCKED,
                plan=plan,
                reason="Planned workspace is no longer available.",
            )

        changed_fields = self._material_changes(plan.truth, fresh_truth)
        if not changed_fields:
            return ReplanDecision(
                disposition=ReplanDisposition.KEEP,
                plan=plan,
                reason="Planning truth is unchanged.",
            )
        if execution_started:
            return ReplanDecision(
                disposition=ReplanDisposition.BLOCKED,
                plan=plan,
                reason=(
                    "Planning truth changed after execution started; "
                    "review is required before semantic replanning."
                ),
            )
        replans_used = plan.revision - 1
        if replans_used >= plan.risk_budget.max_replans:
            return ReplanDecision(
                disposition=ReplanDisposition.BLOCKED,
                plan=plan,
                reason="Automatic replan budget is exhausted.",
            )

        reason = "Planning truth changed: " + ", ".join(changed_fields)
        request_constraints = tuple(
            item for item in plan.constraints if item.source != "project"
        )
        project_constraints = tuple(
            Constraint(description=value, source="project")
            for value in fresh_truth.project_constraints
        )
        revised = plan.model_copy(
            update={
                "revision": plan.revision + 1,
                "replanned_from_revision": plan.revision,
                "replan_reason": reason,
                "truth": fresh_truth,
                "constraints": request_constraints + project_constraints,
            }
        )
        return ReplanDecision(
            disposition=ReplanDisposition.REVISED,
            plan=revised,
            reason=reason,
        )

    @staticmethod
    def _material_changes(
        old: PlanningTruthSnapshot,
        new: PlanningTruthSnapshot,
    ) -> tuple[str, ...]:
        fields = (
            "project_version",
            "project_status",
            "current_phase",
            "workspace",
            "workspace_exists",
            "project_constraints",
        )
        return tuple(
            field for field in fields if getattr(old, field) != getattr(new, field)
        )
