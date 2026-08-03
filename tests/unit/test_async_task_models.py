from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.async_tasks.models import (
    ASYNC_RUN_TRANSITIONS,
    AsyncRunStatus,
    AsyncTaskCreate,
)


def test_terminal_states_have_no_automatic_transitions() -> None:
    for status in (
        AsyncRunStatus.COMPLETED,
        AsyncRunStatus.FAILED,
        AsyncRunStatus.CANCELLED,
    ):
        assert ASYNC_RUN_TRANSITIONS[status] == frozenset()


def test_blocked_can_return_to_pending_for_manual_retry() -> None:
    assert AsyncRunStatus.PENDING in ASYNC_RUN_TRANSITIONS[
        AsyncRunStatus.BLOCKED
    ]


def test_telegram_requires_idempotency_key() -> None:
    with pytest.raises(ValidationError):
        AsyncTaskCreate(
            project_id="proj_1",
            title="Build runner",
            goal="Implement Async Task Runner v1",
            source_channel="telegram",
            source_chat_id="7535966424",
            risk_level=1,
        )


def test_naive_deadline_is_normalized_to_utc() -> None:
    request = AsyncTaskCreate(
        project_id="proj_1",
        title="Build runner",
        goal="Implement Async Task Runner v1",
        source_channel="api",
        deadline=datetime(2026, 7, 28, 12, 0),
    )

    assert request.deadline is not None
    assert request.deadline.tzinfo is UTC
