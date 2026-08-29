from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.models import WorkflowRow
from app.planning.models import Plan, PlanStatus


class PlanPersistenceConflict(ValueError):
    """Persisted workflow identity conflicts with the requested task."""


class PlanRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def save(
        self,
        *,
        workflow_id: str,
        task_id: str,
        plan: Plan,
    ) -> WorkflowRow:
        row = self.session.get(WorkflowRow, workflow_id)
        if row is None:
            row = WorkflowRow(
                id=workflow_id,
                task_id=task_id,
                status=self._status(plan),
            )
            self.session.add(row)
        elif row.task_id != task_id:
            raise PlanPersistenceConflict(
                "Workflow task identity mismatch"
            )

        row.plan_payload = plan.model_dump(mode="json")
        row.status = self._status(plan)
        self.session.flush()
        return row

    def get(self, workflow_id: str) -> Plan | None:
        row = self.session.get(WorkflowRow, workflow_id)
        if row is None or not row.plan_payload:
            return None
        return Plan.model_validate(row.plan_payload)

    @staticmethod
    def _status(plan: Plan) -> str:
        return "blocked" if plan.status is PlanStatus.BLOCKED else "pending"
