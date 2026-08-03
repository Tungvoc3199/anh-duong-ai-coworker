from __future__ import annotations

import json
from hashlib import sha256
from typing import Any

from app.async_tasks.models import AsyncTaskRun
from app.audit import AuditEvent, AuditWriter


def write_async_run_event(
    writer: AuditWriter | None,
    event_type: str,
    run: AsyncTaskRun,
    *,
    actor: str | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    """Append bounded Async Run metadata without raw request data."""
    if writer is None:
        return

    event_payload: dict[str, Any] = {
        "run_id": run.id,
        "status": run.status.value,
        "attempt": run.attempt,
        "version": run.version,
        "idempotency_key_sha256": sha256(
            run.idempotency_key.encode("utf-8")
        ).hexdigest(),
    }
    if payload:
        event_payload.update(payload)

    writer.write(
        AuditEvent(
            event_type=event_type,
            actor=actor,
            task_id=run.task_id,
            project_id=_project_id(run.request_json),
            payload=event_payload,
        )
    )


def _project_id(request_json: str) -> str | None:
    try:
        value = json.loads(request_json)
    except json.JSONDecodeError:
        return None
    if not isinstance(value, dict):
        return None
    project_id = value.get("project_id")
    return project_id if isinstance(project_id, str) else None
