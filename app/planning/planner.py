from __future__ import annotations

from typing import Protocol

from app.planning.models import (
    Constraint,
    DecisionNeeded,
    DefinitionOfDone,
    Goal,
    Plan,
    PlanningRequest,
    PlanningTruthSnapshot,
    PlanNode,
    PlanNodeKind,
    PlanStatus,
    VerificationRequirement,
)


class TruthInspector(Protocol):
    def inspect(
        self,
        project_id: str,
        workspace: str | None,
    ) -> PlanningTruthSnapshot: ...


class GoalPlanner:
    _AMBIGUOUS = frozenset(
        {
            "do it",
            "fix it",
            "improve",
            "làm đi",
            "sửa đi",
            "cải thiện",
        }
    )

    def __init__(self, truth_inspector: TruthInspector) -> None:
        self.truth_inspector = truth_inspector

    def plan(self, request: PlanningRequest) -> Plan:
        truth = self.truth_inspector.inspect(
            request.project_id,
            request.workspace,
        )
        goal = Goal(
            statement=request.outcome.strip(),
            project_id=request.project_id,
        )
        constraints = request.constraints + tuple(
            Constraint(description=value, source="project")
            for value in truth.project_constraints
        )
        definition_of_done = self._definition_of_done(request)
        verification = tuple(
            VerificationRequirement(
                description=f"Verify DoD: {criterion}"
            )
            for criterion in definition_of_done.criteria
        )

        blocker = self._blocker(request, truth)
        if blocker is not None:
            return Plan(
                id=f"plan:{request.request_id}",
                goal=goal,
                definition_of_done=definition_of_done,
                constraints=constraints,
                risk_budget=request.risk_budget,
                deliverables=request.deliverables,
                verification_requirements=verification,
                truth=truth,
                status=PlanStatus.BLOCKED,
                blocker=blocker,
            )

        nodes: list[PlanNode] = []
        dependency: tuple[str, ...] = ()
        if request.approval_required:
            nodes.append(
                PlanNode(
                    id="approval",
                    title="Owner approval",
                    kind=PlanNodeKind.APPROVAL_GATE,
                )
            )
            dependency = ("approval",)

        nodes.append(
            PlanNode(
                id="execute",
                title="Execute minimum plan",
                kind=PlanNodeKind.ACTION,
                depends_on=dependency,
                capability_requirements=request.capability_requirements,
            )
        )
        nodes.append(
            PlanNode(
                id="verify",
                title="Verify definition of done",
                kind=PlanNodeKind.VERIFICATION_GATE,
                depends_on=("execute",),
                verification_requirements=verification,
            )
        )
        return Plan(
            id=f"plan:{request.request_id}",
            goal=goal,
            definition_of_done=definition_of_done,
            constraints=constraints,
            risk_budget=request.risk_budget,
            deliverables=request.deliverables,
            verification_requirements=verification,
            truth=truth,
            status=PlanStatus.READY,
            nodes=tuple(nodes),
        )

    @staticmethod
    def _definition_of_done(
        request: PlanningRequest,
    ) -> DefinitionOfDone:
        if request.definition_of_done is not None:
            return request.definition_of_done
        required = tuple(
            item.description
            for item in request.deliverables
            if item.required
        )
        if required:
            return DefinitionOfDone(
                criteria=tuple(
                    f"Deliverable completed and verified: {item}"
                    for item in required
                ),
                inferred=True,
            )
        return DefinitionOfDone(
            criteria=(
                f"Outcome achieved and verified: {request.outcome.strip()}",
            ),
            inferred=True,
        )

    def _blocker(
        self,
        request: PlanningRequest,
        truth: PlanningTruthSnapshot,
    ) -> DecisionNeeded | None:
        normalized = " ".join(request.outcome.lower().split())
        if normalized in self._AMBIGUOUS and not request.deliverables:
            return DecisionNeeded(
                question="What concrete outcome should be achieved?",
                reason="Goal is too ambiguous to derive a verifiable plan.",
            )
        if request.risk_level > request.risk_budget.max_risk_level:
            return DecisionNeeded(
                question="Should the risk budget be raised or the goal reduced?",
                reason=(
                    f"Risk level {request.risk_level} exceeds budget "
                    f"{request.risk_budget.max_risk_level}."
                ),
            )
        return None
