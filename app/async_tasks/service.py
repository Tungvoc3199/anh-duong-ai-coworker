from __future__ import annotations

import hashlib
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
from app.capabilities.router import CapabilityRouter
from app.db.models import ApprovalRow
from app.planning import (
    Constraint,
    GoalPlanner,
    Plan,
    PlanningRequest,
    PlanningTruthInspector,
    PlanRepository,
)
from app.projects.repository import ProjectRepository
from app.routing.fast_router import FastRouter
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
            request.idempotency_key.strip()
            if request.idempotency_key is not None
            else f"api:{uuid4().hex}"
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

        plan = self._plan(request, idempotency_key) if decision.allowed else None

        if not decision.allowed:
            task = self.task_service.transition(
                task.id,
                TaskStatus.BLOCKED,
                result_summary=(
                    f"{decision.reason_code}: {decision.message}"
                ),
            )
            run_status = AsyncRunStatus.BLOCKED
            error_code = decision.reason_code
            error_message = decision.message
        elif plan is not None and plan.status.value == "blocked":
            task = self.task_service.transition(
                task.id,
                TaskStatus.PLANNING,
            )
            blocker = plan.blocker
            assert blocker is not None
            task = self.task_service.transition(
                task.id,
                TaskStatus.BLOCKED,
                result_summary=blocker.reason,
            )
            run_status = AsyncRunStatus.BLOCKED
            error_code = "planning_blocked"
            error_message = f"{blocker.reason} {blocker.question}"
        else:
            task = self.task_service.transition(
                task.id,
                TaskStatus.PLANNING,
            )
            task = self.task_service.transition(
                task.id,
                TaskStatus.QUEUED,
            )
            run_status = AsyncRunStatus.PENDING
            error_code = None
            error_message = None

        run = self.repository.enqueue(
            task_id=task.id,
            request=request,
            idempotency_key=idempotency_key,
            status=run_status,
            error_code=error_code,
            error_message=error_message,
        )
        session = self.repository.session
        if plan is not None:
            PlanRepository(session).save(
                workflow_id=run.id,
                task_id=task.id,
                plan=plan,
            )
        if request.approval_required and run_status is AsyncRunStatus.PENDING:
            ApprovalService(session).create(
                workflow_id=run.id,
                task_id=task.id,
                action=request.goal,
                risk_level=request.risk_level,
                reason=decision.message,
                preview={"title": request.title, "goal": request.goal},
            )
        return AsyncTaskAccepted(
            task_id=task.id,
            run_id=run.id,
            status=run.status,
            replayed=False,
        )

    def _plan(
        self,
        request: AsyncTaskCreate,
        request_id: str,
    ) -> Plan:
        session = self.repository.session
        route = FastRouter().route(request.goal)
        capability = CapabilityRouter().route(route, request.goal).capability
        planner = GoalPlanner(
            PlanningTruthInspector(ProjectRepository(session))
        )
        planner_request_id = f"planreq_{hashlib.sha256(request_id.encode('utf-8')).hexdigest()}"
        return planner.plan(
            PlanningRequest(
                request_id=planner_request_id,
                project_id=request.project_id,
                outcome=request.goal,
                constraints=tuple(
                    Constraint(description=value)
                    for value in request.constraints
                ),
                risk_level=request.risk_level,
                approval_required=request.approval_required,
                workspace=request.workspace,
                capability_requirements=(capability,),
            )
        )
