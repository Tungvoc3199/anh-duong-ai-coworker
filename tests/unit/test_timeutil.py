from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.timeutil import (
    _ENV_VAR,
    display_tz,
    display_now,
    format_display,
    to_display,
)


@pytest.fixture(autouse=True)
def _clear_display_tz_cache() -> None:
    display_tz.cache_clear()
    yield
    display_tz.cache_clear()


def test_default_display_tz_is_utc_plus_7() -> None:
    offset = display_tz().utcoffset(datetime.now(UTC))
    assert offset is not None
    assert offset.total_seconds() == 7 * 3600


def test_to_display_converts_utc_to_plus_7() -> None:
    value = datetime(2026, 7, 24, 10, 30, tzinfo=UTC)
    local = to_display(value)
    assert local.hour == 17
    assert local.minute == 30
    assert local.utcoffset() is not None
    assert local.utcoffset().total_seconds() == 7 * 3600  # type: ignore[union-attr]
    assert local.astimezone(UTC) == value


def test_to_display_treats_naive_as_utc() -> None:
    local = to_display(datetime(2026, 7, 24, 10, 30))
    assert local.hour == 17


def test_format_display_uses_plus_7_offset() -> None:
    value = datetime(2026, 7, 24, 10, 30, tzinfo=UTC)
    assert format_display(value) == "2026-07-24T17:30:00+07:00"


def test_env_override_with_fixed_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(_ENV_VAR, "UTC+7")
    assert display_tz().utcoffset(datetime.now(UTC)).total_seconds() == 7 * 3600  # type: ignore[union-attr]


def test_env_override_with_iana_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(_ENV_VAR, "America/New_York")
    tz = display_tz()
    assert str(tz) == "America/New_York"


def test_env_override_with_unknown_name_falls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(_ENV_VAR, "Not/A_Real_Zone")
    offset = display_tz().utcoffset(datetime.now(UTC))
    assert offset is not None
    assert offset.total_seconds() == 7 * 3600


def test_display_now_is_in_display_timezone() -> None:
    now = display_now()
    assert now.tzinfo is not None
    assert now.utcoffset() is not None
    assert now.utcoffset().total_seconds() == 7 * 3600  # type: ignore[union-attr]
