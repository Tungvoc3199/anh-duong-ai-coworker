from __future__ import annotations

from app.openclaw.models import (
    GovernanceResult,
    OpenClawExecutionResult,
    OpenClawTransportError,
)
from app.planning.failure import ExecutionFailureClass, ExecutionFailureClassifier
from app.planning.outcome import OutcomeDisposition, OutcomeJudgement


def _judgement(reason_code: str) -> OutcomeJudgement:
    return OutcomeJudgement(
        disposition=OutcomeDisposition.REPLAN,
        reason_code=reason_code,
        reason="needs repair",
    )


def test_classifier_distinguishes_retryable_transport_from_uncertain_side_effect() -> None:
    classifier = ExecutionFailureClassifier()
    retryable = OpenClawTransportError(
        "connection_error",
        "connection failed",
        retryable=True,
    )
    uncertain = OpenClawTransportError(
        "timeout",
        "timed out",
        retryable=False,
        uncertain_side_effect=True,
    )

    assert (
        classifier.classify(transport_error=retryable) is ExecutionFailureClass.RETRYABLE_TRANSPORT
    )
    assert (
        classifier.classify(transport_error=uncertain)
        is ExecutionFailureClass.UNCERTAIN_SIDE_EFFECT
    )


def test_classifier_keeps_policy_and_governance_failures_fail_closed() -> None:
    classifier = ExecutionFailureClassifier()
    governance = GovernanceResult(
        decision="deny",
        status="denied",
        reason="policy denied change",
    )
    result = OpenClawExecutionResult(
        outcome="failed",
        summary="denied",
        governance_result=governance,
    )

    assert classifier.classify(policy_blocked=True) is ExecutionFailureClass.POLICY_BLOCKED
    assert classifier.classify(result=result) is ExecutionFailureClass.GOVERNANCE_FAILURE


def test_classifier_maps_only_dod_failures_to_semantic_replan_classes() -> None:
    classifier = ExecutionFailureClassifier()

    missing = classifier.classify(judgement=_judgement("dod_evidence_missing"))
    unmet = classifier.classify(judgement=_judgement("dod_unmet"))
    unknown = classifier.classify(judgement=_judgement("unexpected"))

    assert missing is ExecutionFailureClass.DOD_EVIDENCE_MISSING
    assert unmet is ExecutionFailureClass.DOD_UNMET_RECOVERABLE
    assert unknown is ExecutionFailureClass.UNKNOWN
    assert classifier.allows_semantic_replan(missing) is True
    assert classifier.allows_semantic_replan(unmet) is True
    assert classifier.allows_semantic_replan(unknown) is False
    assert classifier.allows_semantic_replan(ExecutionFailureClass.GOVERNANCE_FAILURE) is False
