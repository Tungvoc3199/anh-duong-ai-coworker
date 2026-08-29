from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.capabilities.models import CapabilityKind
from app.planning.models import (
    Constraint,
    DefinitionOfDone,
    Deliverable,
    Goal,
    Plan,
    PlanningRequest,
    PlanNode,
    PlanNodeKind,
    PlanStatus,
    RiskBudget,
    VerificationRequirement,
)
from app.planning.planner import GoalPlanner
from app.planning.truth import PlanningTruthSnapshot


class StubTruthInspector:
    def __init__(self, snapshot: PlanningTruthSnapshot) -> None:
        self.snapshot = snapshot
        self.calls: list[str] = []

    def inspect(self, project_id: str, workspace: str | None) -> PlanningTruthSnapshot:
        self.calls.append(project_id)
        return self.snapshot


def _truth(*, workspace_exists: bool = True) -> PlanningTruthSnapshot:
    return PlanningTruthSnapshot(
        project_id="proj_1",
        project_version=3,
        project_status="active",
        current_phase="L5",
        workspace="/tmp/project",
        workspace_exists=workspace_exists,
        project_constraints=("preserve governance",),
    )


def _request(**overrides: object) -> PlanningRequest:
    data: dict[str, object] = {
        "request_id": "req_1",
        "project_id": "proj_1",
        "outcome": "Implement durable goal planning with explicit verification",
        "deliverables": (Deliverable(description="planner implementation"),),
        "constraints": (Constraint(description="do not bypass Core"),),
        "risk_budget": RiskBudget(max_risk_level=2, max_plan_nodes=8),
        "risk_level": 1,
        "approval_required": True,
        "workspace": "/tmp/project",
        "capability_requirements": (CapabilityKind.PLANNING,),
    }
    data.update(overrides)
    return PlanningRequest(**data)


def test_plan_rejects_cycles() -> None:
    with pytest.raises(ValidationError, match="acyclic"):
        Plan(
            id="plan_1",
            goal=Goal(statement="Ship planner", project_id="proj_1"),
            definition_of_done=DefinitionOfDone(criteria=("planner verified",)),
            constraints=(),
            risk_budget=RiskBudget(),
            deliverables=(),
            verification_requirements=(
                VerificationRequirement(description="tests pass"),
            ),
            truth=_truth(),
            status=PlanStatus.READY,
            nodes=(
                PlanNode(
                    id="a",
                    title="A",
                    kind=PlanNodeKind.ACTION,
                    depends_on=("b",),
                    capability_requirements=(CapabilityKind.PLANNING,),
                ),
                PlanNode(
                    id="b",
                    title="B",
                    kind=PlanNodeKind.VERIFICATION_GATE,
                    depends_on=("a",),
                ),
            ),
        )


def test_planner_inspects_truth_and_emits_explicit_gates() -> None:
    inspector = StubTruthInspector(_truth())
    plan = GoalPlanner(inspector).plan(_request())

    assert inspector.calls == ["proj_1"]
    assert plan.status is PlanStatus.READY
    assert plan.truth.project_version == 3
    kinds = [node.kind for node in plan.nodes]
    assert PlanNodeKind.APPROVAL_GATE in kinds
    assert kinds[-1] is PlanNodeKind.VERIFICATION_GATE
    assert all(
        not hasattr(node, "model_name") and not hasattr(node, "provider")
        for node in plan.nodes
    )
    assert any(
        CapabilityKind.PLANNING in node.capability_requirements
        for node in plan.nodes
        if node.kind is PlanNodeKind.ACTION
    )


@pytest.mark.parametrize("outcome", ["do it", "fix it", "improve"])
def test_ambiguous_goal_returns_one_concrete_blocker(outcome: str) -> None:
    plan = GoalPlanner(StubTruthInspector(_truth())).plan(
        _request(outcome=outcome, deliverables=())
    )

    assert plan.status is PlanStatus.BLOCKED
    assert plan.blocker is not None
    assert plan.blocker.question
    assert plan.blocker.reason
    assert len(plan.nodes) == 0


def test_missing_workspace_is_recorded_without_overriding_policy() -> None:
    plan = GoalPlanner(StubTruthInspector(_truth(workspace_exists=False))).plan(
        _request()
    )

    assert plan.status is PlanStatus.READY
    assert plan.blocker is None
    assert plan.truth.workspace_exists is False
    assert plan.nodes[-1].kind is PlanNodeKind.VERIFICATION_GATE
