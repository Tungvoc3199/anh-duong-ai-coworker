from __future__ import annotations

from app.capabilities.models import CapabilityKind
from app.planning.models import (
    DefinitionOfDone,
    ExecutionBudget,
    Goal,
    Plan,
    PlanningTruthSnapshot,
    PlanNode,
    PlanNodeExecution,
    PlanNodeKind,
    PlanNodeState,
    PlanStatus,
    RiskBudget,
)
from app.planning.scheduler import PlanNodeScheduler


def _truth() -> PlanningTruthSnapshot:
    return PlanningTruthSnapshot(
        project_id="proj_1",
        project_version=1,
        project_status="active",
        workspace="/tmp/project",
        workspace_exists=True,
    )


def _plan(*, executions: tuple[PlanNodeExecution, ...] = ()) -> Plan:
    return Plan(
        id="plan_1",
        goal=Goal(statement="Complete a two-step job", project_id="proj_1"),
        definition_of_done=DefinitionOfDone(criteria=("job verified",)),
        constraints=(),
        risk_budget=RiskBudget(),
        deliverables=(),
        verification_requirements=(),
        truth=_truth(),
        status=PlanStatus.READY,
        nodes=(
            PlanNode(
                id="collect",
                title="Collect evidence",
                kind=PlanNodeKind.ACTION,
                capability_requirements=(CapabilityKind.PROJECT_READ,),
            ),
            PlanNode(
                id="analyze",
                title="Analyze evidence",
                kind=PlanNodeKind.ACTION,
                depends_on=("collect",),
                capability_requirements=(CapabilityKind.PLANNING,),
            ),
            PlanNode(
                id="verify",
                title="Verify DoD",
                kind=PlanNodeKind.VERIFICATION_GATE,
                depends_on=("analyze",),
            ),
        ),
        node_executions=executions,
    )


def test_scheduler_returns_only_dependency_ready_nodes_in_plan_order() -> None:
    scheduler = PlanNodeScheduler()

    first = scheduler.ready_nodes(_plan())
    assert [node.id for node in first] == ["collect"]

    second = scheduler.ready_nodes(
        _plan(
            executions=(
                PlanNodeExecution(
                    node_id="collect",
                    state=PlanNodeState.COMPLETED,
                ),
            )
        )
    )
    assert [node.id for node in second] == ["analyze"]

    third = scheduler.ready_nodes(
        _plan(
            executions=(
                PlanNodeExecution(node_id="collect", state=PlanNodeState.COMPLETED),
                PlanNodeExecution(node_id="analyze", state=PlanNodeState.COMPLETED),
            )
        )
    )
    assert [node.id for node in third] == ["verify"]


def test_scheduler_excludes_non_pending_nodes() -> None:
    plan = _plan(
        executions=(
            PlanNodeExecution(node_id="collect", state=PlanNodeState.COMPLETED),
            PlanNodeExecution(node_id="analyze", state=PlanNodeState.RUNNING),
        )
    )

    assert PlanNodeScheduler().ready_nodes(plan) == ()
    assert PlanNodeScheduler().state_for(plan, "verify") is PlanNodeState.PENDING


def test_legacy_plan_payload_loads_execution_defaults() -> None:
    legacy = _plan().model_dump(mode="json")
    legacy.pop("node_executions", None)
    legacy.pop("evidence", None)
    legacy.pop("execution_budget", None)
    legacy.pop("outcome_judgement", None)

    loaded = Plan.model_validate(legacy)

    assert loaded.node_executions == ()
    assert loaded.evidence == ()
    assert loaded.execution_budget == ExecutionBudget()
    assert loaded.outcome_judgement is None
