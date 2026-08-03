from __future__ import annotations

from uuid import uuid4

from app.async_tasks.models import (
    AsyncRunStatus,
    AsyncTaskAccepted,
    AsyncTaskCreate,
)
from app.async_tasks.policy import AsyncTaskPolicyGate
from app.async_tasks.repository import AsyncTaskRepository
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
        )
        return AsyncTaskAccepted(
            task_id=task.id,
            run_id=run.id,
            status=run.status,
            replayed=False,
        )
