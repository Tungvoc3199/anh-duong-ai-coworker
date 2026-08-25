from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from app.approvals import ApprovalService
from app.async_tasks.models import (
    AsyncRunStatus,
    AsyncTaskAccepted,
    AsyncTaskCreate,
)
from app.async_tasks.policy import AsyncTaskPolicyGate
from app.async_tasks.repository import AsyncTaskRepository
from app.db.models import ApprovalRow, WorkflowRow
from app.tasks import TaskCreate, TaskService, TaskStatus


class AsyncTaskService:
    def __init__(
        self,
        *,
        task_service: TaskService,
        repository: AsyncTaskRepository,
        policy_gate: AsyncTaskPolicyGate,
    ) -> None:
        self.task_service = task_service
        self.repository = repository
        self.policy_gate = policy_gate

    def resolve_approval(
        self,
        approval_id: str,
        *,

        resolved_by: str,
        approved: bool,
        action: str,
    ) -> ApprovalRow:
        session = self.repository.session
        approval = session.get(ApprovalRow, approval_id)
        if approval is None:
            raise ValueError("Approval not found.")
        resolved = ApprovalService(session).resolve(
            approval_id,
            workflow_id=approval.workflow_id,
            task_id=approval.task_id,
            action=action,
            resolved_by=resolved_by,
            approved=approved,
        )
        if approved:
            self.repository.transition(
                approval.workflow_id,
                AsyncRunStatus.PENDING,
                now=datetime.now(UTC),
            )
            task = self.task_service.get(approval.task_id)
            if task.status is not TaskStatus.QUEUED:
                self.task_service.transition(approval.task_id, TaskStatus.QUEUED)
        return resolved

    def create(
        self,
        request: AsyncTaskCreate,
    ) -> AsyncTaskAccepted:
        idempotency_key = (
            request.idempotency_key
            or f"api:{uuid4().hex}"
        )
        if request.idempotency_key is not None:
            self.repository.acquire_sqlite_write_lock()
        existing = self.repository.get_by_idempotency_key(
            idempotency_key
        )
        if existing is not None:
            return AsyncTaskAccepted(
                task_id=existing.task_id,
                run_id=existing.id,
                status=existing.status,
                replayed=True,
            )

        decision = self.policy_gate.evaluate(request)
        task = self.task_service.create(
            TaskCreate(
                project_id=request.project_id,
                title=request.title,
                description=request.goal,
                priority=request.priority,
                risk_level=request.risk_level,
                requested_by=request.requested_by,
                source_channel=request.source_channel,
                approval_required=request.approval_required,
                deadline=request.deadline,
            )
        )

        if decision.allowed:
            task = self.task_service.transition(
                task.id,
                TaskStatus.PLANNING,
            )
            task = self.task_service.transition(
                task.id,
                TaskStatus.QUEUED,
            )
            run_status = AsyncRunStatus.PENDING
        else:
            task = self.task_service.transition(
                task.id,
                TaskStatus.BLOCKED,
                result_summary=(
                    f"{decision.reason_code}: {decision.message}"
                ),
            )
            run_status = AsyncRunStatus.BLOCKED

        run = self.repository.enqueue(
            task_id=task.id,
            request=request,
            idempotency_key=idempotency_key,
            status=run_status,
            error_code=(
                decision.reason_code
                if not decision.allowed
                else None
            ),
            error_message=(
                decision.message if not decision.allowed else None
            ),
        )
        if request.approval_required:
            session = self.repository.session
            session.add(WorkflowRow(id=run.id, task_id=task.id, status="blocked"))
            session.flush()
            ApprovalService(session).create(
                workflow_id=run.id,
                task_id=task.id,
                action=request.goal,
                risk_level=request.risk_level,
                reason=decision.message,
                preview={'title': request.title, 'goal': request.goal},
            )
        return AsyncTaskAccepted(
            task_id=task.id,
            run_id=run.id,
            status=run.status,
            replayed=False,
        )
