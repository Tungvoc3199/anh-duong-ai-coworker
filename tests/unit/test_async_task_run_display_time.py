from __future__ import annotations

from datetime import UTC, datetime

from app.async_tasks.models import (
    AsyncRunStatus,
    AsyncTaskMode,
    AsyncTaskRun,
    NotificationStatus,
)
from app.tasks.models import TaskPriority


def _run(*, now: datetime) -> AsyncTaskRun:
    return AsyncTaskRun(
        id="run_1234567890abcdef",
        task_id="task_1234567890abcdef",
        status=AsyncRunStatus.COMPLETED,
        mode=AsyncTaskMode.QUICK,
        goal="Test goal",
        workspace="/mnt/f/AIOS",
        request_json='{"goal": "Test goal"}',
        checkpoint_json=None,
        result_json=None,
        attempt=1,
        max_attempts=3,
        run_after=now,
        lease_owner=None,
        lease_expires_at=None,
        idempotency_key="key_1",
        external_run_id=None,
        last_error_code=None,
        last_error_message=None,
        source_chat_id="chat_1",
        notification_status=NotificationStatus.NOT_REQUIRED,
        notification_attempts=0,
        created_at=now,
        updated_at=now,
        version=1,
    )


def test_json_serialization_uses_display_timezone_plus_7() -> None:
    now = datetime(2026, 7, 24, 10, 30, tzinfo=UTC)
    run = _run(now=now)

    payload = run.model_dump(mode="json")

    assert payload["created_at"] == "2026-07-24T17:30:00+07:00"
    assert payload["updated_at"] == "2026-07-24T17:30:00+07:00"
    assert payload["run_after"] == "2026-07-24T17:30:00+07:00"
    assert payload["lease_expires_at"] is None


def test_python_attribute_values_stay_utc() -> None:
    now = datetime(2026, 7, 24, 10, 30, tzinfo=UTC)
    run = _run(now=now)

    # Internal logic keeps UTC; only JSON output is display-localized.
    assert run.created_at == now
    assert run.created_at.utcoffset().total_seconds() == 0  # type: ignore[union-attr]
    assert run.created_at.hour == 10
    assert run.updated_at == now
    assert run.run_after == now


def test_naive_sqlite_datetime_is_normalized_to_utc_then_displayed() -> None:
    now = datetime(2026, 7, 24, 10, 30)
    run = _run(now=now)

    assert run.created_at.tzinfo is not None
    payload = run.model_dump(mode="json")
    assert payload["created_at"] == "2026-07-24T17:30:00+07:00"
