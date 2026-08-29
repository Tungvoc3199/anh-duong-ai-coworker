from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.capabilities.models import CapabilityKind
from app.planning.models import (
    Constraint,
    Deliverable,
    PlanningRequest,
    PlanningTruthSnapshot,
    RiskBudget,
)
from app.planning.planner import GoalPlanner


class StubTruthInspector:
    def __init__(self, snapshot: PlanningTruthSnapshot) -> None:
        self.snapshot = snapshot

    def inspect(
        self,
        project_id: str,
        workspace: str | None,
    ) -> PlanningTruthSnapshot:
        return self.snapshot


def _truth(
    *,
    version: int = 1,
    status: str = "active",
    phase: str = "L5-08",
    workspace_exists: bool = True,
    constraints: tuple[str, ...] = ("preserve governance",),
    observed_at: datetime | None = None,
) -> PlanningTruthSnapshot:
    return PlanningTruthSnapshot(
        project_id="proj_1",
        project_version=version,
        project_status=status,
        current_phase=phase,
        workspace="/tmp/project",
        workspace_exists=workspace_exists,
        project_constraints=constraints,
        observed_at=observed_at,
    )


def _plan(
    *,
    max_replans: int = 3,
    revision: int = 1,
    workspace_exists: bool = True,
):
    plan = GoalPlanner(
        StubTruthInspector(_truth(workspace_exists=workspace_exists))
    ).plan(
        PlanningRequest(
            request_id="req_1",
            project_id="proj_1",
            outcome="Implement scheduler safely",
            deliverables=(Deliverable(description="scheduler"),),
            constraints=(Constraint(description="do not bypass Core"),),
            risk_budget=RiskBudget(max_replans=max_replans),
            risk_level=1,
            workspace="/tmp/project",
            capability_requirements=(CapabilityKind.PLANNING,),
        )
    )
    return plan.model_copy(update={"revision": revision})


def test_replanner_ignores_observation_timestamp_only() -> None:
    from app.planning.replanner import PlanReplanner, ReplanDisposition

    original = _plan()
    fresh = _truth(
        observed_at=datetime(2026, 8, 29, 15, 0, tzinfo=UTC)
    )

    decision = PlanReplanner().reconcile(original, fresh, execution_started=False)

    assert decision.disposition is ReplanDisposition.KEEP
    assert decision.plan == original


def test_replanner_revises_safe_truth_drift_and_refreshes_project_constraints() -> None:
    from app.planning.replanner import PlanReplanner, ReplanDisposition

    original = _plan()
    fresh = _truth(
        version=2,
        phase="L5-08-runtime",
        constraints=("preserve governance", "use isolated worktree"),
    )

    decision = PlanReplanner().reconcile(original, fresh, execution_started=False)

    assert decision.disposition is ReplanDisposition.REVISED
    assert decision.plan.revision == 2
    assert decision.plan.replanned_from_revision == 1
    assert decision.plan.replan_reason
    assert decision.plan.truth == fresh
    assert decision.plan.nodes == original.nodes
    request_constraints = [
        item.description for item in decision.plan.constraints if item.source == "request"
    ]
    project_constraints = [
        item.description for item in decision.plan.constraints if item.source == "project"
    ]
    assert request_constraints == ["do not bypass Core"]
    assert project_constraints == [
        "preserve governance",
        "use isolated worktree",
    ]


@pytest.mark.parametrize(
    "status", ["idea", "planned", "paused", "blocked", "completed", "archived"]
)
def test_replanner_blocks_non_executable_project_truth(status: str) -> None:
    from app.planning.replanner import PlanReplanner, ReplanDisposition

    decision = PlanReplanner().reconcile(
        _plan(),
        _truth(version=2, status=status),
        execution_started=False,
    )

    assert decision.disposition is ReplanDisposition.BLOCKED
    assert status in decision.reason


def test_replanner_blocks_when_workspace_disappears() -> None:
    from app.planning.replanner import PlanReplanner, ReplanDisposition

    decision = PlanReplanner().reconcile(
        _plan(),
        _truth(workspace_exists=False),
        execution_started=False,
    )

    assert decision.disposition is ReplanDisposition.BLOCKED
    assert "workspace" in decision.reason.lower()


def test_replanner_blocks_when_workspace_was_already_missing() -> None:
    from app.planning.replanner import PlanReplanner, ReplanDisposition

    decision = PlanReplanner().reconcile(
        _plan(workspace_exists=False),
        _truth(workspace_exists=False),
        execution_started=False,
    )

    assert decision.disposition is ReplanDisposition.BLOCKED
    assert "workspace" in decision.reason.lower()


def test_replanner_blocks_truth_drift_after_execution_started() -> None:
    from app.planning.replanner import PlanReplanner, ReplanDisposition

    decision = PlanReplanner().reconcile(
        _plan(),
        _truth(version=2, phase="changed"),
        execution_started=True,
    )

    assert decision.disposition is ReplanDisposition.BLOCKED
    assert "execution" in decision.reason.lower()


def test_replanner_blocks_when_replan_budget_is_exhausted() -> None:
    from app.planning.replanner import PlanReplanner, ReplanDisposition

    decision = PlanReplanner().reconcile(
        _plan(max_replans=1, revision=2),
        _truth(version=2, phase="changed"),
        execution_started=False,
    )

    assert decision.disposition is ReplanDisposition.BLOCKED
    assert "replan" in decision.reason.lower()


def test_replanner_is_exposed_from_planning_package() -> None:
    from app.planning import (
        PlanReplanner,
        ReplanDecision,
        ReplanDisposition,
    )

    assert PlanReplanner is not None
    assert ReplanDecision is not None
    assert ReplanDisposition is not None
