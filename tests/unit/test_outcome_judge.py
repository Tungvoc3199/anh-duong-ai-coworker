from __future__ import annotations

from app.openclaw.models import CriterionVerification, OpenClawExecutionResult
from app.planning.models import (
    DefinitionOfDone,
    Goal,
    Plan,
    PlanningTruthSnapshot,
    PlanNode,
    PlanNodeKind,
    PlanStatus,
    RiskBudget,
)
from app.planning.outcome import OutcomeDisposition, OutcomeJudge


def _plan() -> Plan:
    return Plan(
        id="plan_1",
        goal=Goal(statement="Produce verified artifact", project_id="proj_1"),
        definition_of_done=DefinitionOfDone(criteria=("artifact exists", "tests pass")),
        constraints=(),
        risk_budget=RiskBudget(),
        deliverables=(),
        verification_requirements=(),
        truth=PlanningTruthSnapshot(
            project_id="proj_1",
            project_version=1,
            project_status="active",
            workspace="/tmp/project",
            workspace_exists=True,
        ),
        status=PlanStatus.READY,
        nodes=(
            PlanNode(
                id="execute",
                title="Execute",
                kind=PlanNodeKind.ACTION,
            ),
            PlanNode(
                id="verify",
                title="Verify",
                kind=PlanNodeKind.VERIFICATION_GATE,
                depends_on=("execute",),
            ),
        ),
    )


def test_completed_without_criterion_evidence_requests_replan() -> None:
    judgement = OutcomeJudge().judge(
        _plan(),
        OpenClawExecutionResult(outcome="completed", summary="done"),
    )

    assert judgement.disposition is OutcomeDisposition.REPLAN
    assert judgement.reason_code == "dod_evidence_missing"


def test_blocked_or_failed_model_result_cannot_be_satisfied() -> None:
    blocked = OutcomeJudge().judge(
        _plan(),
        OpenClawExecutionResult(outcome="blocked", summary="need input"),
    )
    failed = OutcomeJudge().judge(
        _plan(),
        OpenClawExecutionResult(outcome="failed", summary="failed"),
    )

    assert blocked.disposition is OutcomeDisposition.BLOCKED
    assert failed.disposition is OutcomeDisposition.FAILED


def test_all_exact_dod_criteria_verified_with_evidence_satisfies_goal() -> None:
    result = OpenClawExecutionResult(
        outcome="completed",
        summary="verified",
        criterion_verification=(
            CriterionVerification(
                criterion="artifact exists",
                status="verified",
                evidence_refs=("ev_artifact",),
            ),
            CriterionVerification(
                criterion="tests pass",
                status="verified",
                evidence_refs=("ev_tests",),
            ),
        ),
    )

    judgement = OutcomeJudge().judge(_plan(), result)

    assert judgement.disposition is OutcomeDisposition.SATISFIED
    assert judgement.reason_code == "dod_satisfied"
    assert all(item.satisfied for item in judgement.criteria)


def test_unknown_or_unmet_criterion_never_certifies_success() -> None:
    result = OpenClawExecutionResult(
        outcome="completed",
        summary="partial",
        criterion_verification=(
            CriterionVerification(
                criterion="artifact exists",
                status="verified",
                evidence_refs=("ev_artifact",),
            ),
            CriterionVerification(
                criterion="tests pass",
                status="unknown",
                explanation="test evidence missing",
            ),
        ),
    )

    judgement = OutcomeJudge().judge(_plan(), result)
    assert judgement.disposition is OutcomeDisposition.REPLAN
    assert judgement.reason_code == "dod_evidence_missing"
