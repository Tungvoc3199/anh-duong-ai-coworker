from __future__ import annotations

from enum import StrEnum

from app.openclaw.models import OpenClawExecutionResult, OpenClawTransportError
from app.planning.outcome import OutcomeJudgement


class ExecutionFailureClass(StrEnum):
    RETRYABLE_TRANSPORT = "retryable_transport"
    UNCERTAIN_SIDE_EFFECT = "uncertain_side_effect"
    POLICY_BLOCKED = "policy_blocked"
    APPROVAL_REQUIRED = "approval_required"
    GOVERNANCE_FAILURE = "governance_failure"
    DOD_EVIDENCE_MISSING = "dod_evidence_missing"
    DOD_UNMET_RECOVERABLE = "dod_unmet_recoverable"
    EXECUTION_FAILED = "execution_failed"
    BUDGET_EXHAUSTED = "budget_exhausted"
    UNKNOWN = "unknown"


class ExecutionFailureClassifier:
    _SEMANTIC_REPLAN = frozenset(
        {
            ExecutionFailureClass.DOD_EVIDENCE_MISSING,
            ExecutionFailureClass.DOD_UNMET_RECOVERABLE,
        }
    )

    def classify(
        self,
        *,
        result: OpenClawExecutionResult | None = None,
        judgement: OutcomeJudgement | None = None,
        transport_error: OpenClawTransportError | None = None,
        policy_blocked: bool = False,
        approval_required: bool = False,
        budget_exhausted: bool = False,
    ) -> ExecutionFailureClass:
        if budget_exhausted:
            return ExecutionFailureClass.BUDGET_EXHAUSTED
        if policy_blocked:
            return ExecutionFailureClass.POLICY_BLOCKED
        if approval_required:
            return ExecutionFailureClass.APPROVAL_REQUIRED
        if transport_error is not None:
            if transport_error.uncertain_side_effect:
                return ExecutionFailureClass.UNCERTAIN_SIDE_EFFECT
            if transport_error.retryable:
                return ExecutionFailureClass.RETRYABLE_TRANSPORT
            return ExecutionFailureClass.EXECUTION_FAILED
        if result is not None and result.governance_result is not None:
            governance = result.governance_result
            if governance.decision != "allow" or governance.status not in {"verified", "approved"}:
                return ExecutionFailureClass.GOVERNANCE_FAILURE
        if judgement is not None:
            if judgement.reason_code == "dod_evidence_missing":
                return ExecutionFailureClass.DOD_EVIDENCE_MISSING
            if judgement.reason_code == "dod_unmet":
                return ExecutionFailureClass.DOD_UNMET_RECOVERABLE
            if judgement.reason_code == "execution_failed":
                return ExecutionFailureClass.EXECUTION_FAILED
            return ExecutionFailureClass.UNKNOWN
        if result is not None and result.outcome == "failed":
            return ExecutionFailureClass.EXECUTION_FAILED
        return ExecutionFailureClass.UNKNOWN

    @classmethod
    def allows_semantic_replan(cls, failure_class: ExecutionFailureClass) -> bool:
        return failure_class in cls._SEMANTIC_REPLAN
