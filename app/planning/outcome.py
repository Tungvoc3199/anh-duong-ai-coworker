from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from app.openclaw.models import OpenClawExecutionResult
from app.planning.models import Plan


class OutcomeDisposition(StrEnum):
    SATISFIED = "satisfied"
    REPLAN = "replan"
    BLOCKED = "blocked"
    FAILED = "failed"


class CriterionJudgement(BaseModel):
    model_config = ConfigDict(frozen=True)
    criterion: str
    satisfied: bool
    status: str
    reason: str


class OutcomeJudgement(BaseModel):
    model_config = ConfigDict(frozen=True)
    disposition: OutcomeDisposition
    criteria: tuple[CriterionJudgement, ...] = ()
    reason_code: str
    reason: str


class OutcomeJudge:
    @staticmethod
    def _normalize(value: str) -> str:
        return " ".join(value.split())

    def judge(self, plan: Plan, result: OpenClawExecutionResult) -> OutcomeJudgement:
        if result.outcome == "blocked":
            return OutcomeJudgement(
                disposition=OutcomeDisposition.BLOCKED,
                reason_code="execution_blocked",
                reason=result.summary,
            )
        if result.outcome == "failed":
            return OutcomeJudgement(
                disposition=OutcomeDisposition.FAILED,
                reason_code="execution_failed",
                reason=result.summary,
            )

        by_criterion = {}
        for item in result.criterion_verification:
            key = self._normalize(item.criterion)
            by_criterion[key] = item

        checks: list[CriterionJudgement] = []
        saw_unmet = False
        for criterion in plan.definition_of_done.criteria:
            item = by_criterion.get(self._normalize(criterion))
            if item is None:
                checks.append(
                    CriterionJudgement(
                        criterion=criterion,
                        satisfied=False,
                        status="unknown",
                        reason="No criterion evidence was returned.",
                    )
                )
                continue
            if item.status == "verified" and item.evidence_refs:
                checks.append(
                    CriterionJudgement(
                        criterion=criterion,
                        satisfied=True,
                        status="verified",
                        reason="Verified by explicit evidence references.",
                    )
                )
                continue
            saw_unmet = saw_unmet or item.status == "unmet"
            reason = item.explanation or (
                "Verified status lacked evidence references."
                if item.status == "verified"
                else "Criterion is not verified."
            )
            checks.append(
                CriterionJudgement(
                    criterion=criterion, satisfied=False, status=item.status, reason=reason
                )
            )

        if checks and all(item.satisfied for item in checks):
            return OutcomeJudgement(
                disposition=OutcomeDisposition.SATISFIED,
                criteria=tuple(checks),
                reason_code="dod_satisfied",
                reason="All definition-of-done criteria are verified by evidence.",
            )
        return OutcomeJudgement(
            disposition=OutcomeDisposition.REPLAN,
            criteria=tuple(checks),
            reason_code=("dod_unmet" if saw_unmet else "dod_evidence_missing"),
            reason="Definition of done is not fully verified by evidence.",
        )
