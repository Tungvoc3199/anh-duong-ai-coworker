from __future__ import annotations

import json
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session, sessionmaker

from app.async_tasks.models import (
    AsyncTaskCreate,
    NotificationStatus,
)
from app.async_tasks.policy import AsyncTaskPolicyGate
from app.async_tasks.repository import AsyncTaskRepository
from app.audit import AuditWriter
from app.tasks import TaskRepository, TaskService, TaskStatus


class RecoverySummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    requeued: int = 0
    blocked: int = 0
    policy_unblocked: int = 0


def recover_stale_runs(
    session_factory: sessionmaker[Session],
    *,
    now: datetime | None = None,
    audit_writer: AuditWriter | None = None,
    policy_gate: AsyncTaskPolicyGate | None = None,
) -> RecoverySummary:
    timestamp = _utc(now)
    requeued = 0
    blocked = 0
    policy_unblocked = 0

    with session_factory() as session:
        repository = AsyncTaskRepository(
            session,
            audit_writer=audit_writer,
        )
        stale_runs = repository.list_stale_leases(
            now=timestamp
        )

        for run in stale_runs:
            request = AsyncTaskCreate.model_validate_json(
                run.request_json
            )
            checkpoint = _checkpoint(run.checkpoint_json)
            uncertain = bool(
                checkpoint.get("uncertain_side_effect", False)
            )
            safe = (
                request.risk_level == 0
                or (
                    request.risk_level == 1
                    and bool(run.idempotency_key)
                    and not uncertain
                )
            )
            recovered = repository.recover_stale(
                run.id,
                safe_to_requeue=safe,
                now=timestamp,
                reason=(
                    "Stale lease recovered safely."
                    if safe
                    else (
                        "Stale lease was blocked because risk or "
                        "side-effect certainty does not allow replay."
                    )
                ),
            )

            if safe:
                requeued += 1
                continue

            blocked += 1
            if recovered.source_chat_id:
                repository.mark_notification(
                    run.id,
                    status=NotificationStatus.PENDING,
                    now=timestamp,
                )
            if audit_writer is not None:
                task_service = TaskService(
                    TaskRepository(session),
                    audit_writer,
                )
                task = task_service.get(run.task_id)
                if task.status in {
                    TaskStatus.QUEUED,
                    TaskStatus.RUNNING,
                    TaskStatus.VERIFYING,
                }:
                    task_service.transition(
                        task.id,
                        TaskStatus.BLOCKED,
                        result_summary=(
                            "Stale run blocked because replay is "
                            "not proven safe."
                        ),
                    )

        if policy_gate is not None:
            task_service = TaskService(
                TaskRepository(session),
                audit_writer,
            )
            for run in repository.list_legacy_approval_blocked_runs():
                request = AsyncTaskCreate.model_validate_json(
                    run.request_json
                )
                decision = policy_gate.evaluate(request)
                if decision.reason_code != "allowed_with_step_gates":
                    continue
                recovered = repository.manual_retry(
                    run.id,
                    now=timestamp,
                )
                task_service.transition(
                    recovered.task_id,
                    TaskStatus.QUEUED,
                    result_summary=(
                        "Legacy approval block requeued after "
                        "policy allowed step-level execution."
                    ),
                )
                policy_unblocked += 1

        session.commit()

    return RecoverySummary(
        requeued=requeued,
        blocked=blocked,
        policy_unblocked=policy_unblocked,
    )


def _checkpoint(value: str | None) -> dict[str, object]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _utc(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
