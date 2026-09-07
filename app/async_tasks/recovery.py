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

        # A blocked approval is a durable owner decision boundary, not a
        # crashed lease. Restart must not manual_retry it or reset its sent
        # notification. Explicit approval/continuation APIs own that transition.
        # Keep policy_gate/policy_unblocked in the public contract for callers.

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
