"""Display-time helpers.

Storage and business logic stay in UTC. This module converts datetimes to
the configured display timezone at human-facing output boundaries only.

The display timezone is read from the ``ANH_DUONG_DISPLAY_TIMEZONE``
environment variable (IANA name, e.g. ``Asia/Ho_Chi_Minh``) and defaults to
Asia/Ho_Chi_Minh (UTC+7, Vietnam, no DST).
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone, tzinfo
from functools import lru_cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# Aliases that resolve to the fixed UTC+7 offset (Vietnam has no DST).
_FIXED_OFFSET_ALIASES = frozenset(
    {"utc+7", "+07:00", "+7", "ict", "vietnam", "vn"}
)

_DEFAULT_DISPLAY_TZ_NAME = "Asia/Ho_Chi_Minh"
_FALLBACK_TZ = timezone(timedelta(hours=7), name="UTC+7")
_ENV_VAR = "ANH_DUONG_DISPLAY_TIMEZONE"


@lru_cache(maxsize=1)
def display_tz() -> tzinfo:
    """Return the configured display timezone (UTC+7 by default)."""
    name = os.environ.get(_ENV_VAR, "").strip() or _DEFAULT_DISPLAY_TZ_NAME
    if name.casefold() in _FIXED_OFFSET_ALIASES:
        return _FALLBACK_TZ
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        # Never fail display formatting because of a bad tz name; fall back
        # to the default UTC+7 (Vietnam, no DST).
        return _FALLBACK_TZ


def to_display(value: datetime) -> datetime:
    """Convert an aware datetime to the display timezone.

    Naive datetimes are treated as UTC (the storage convention).
    """
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(display_tz())


def format_display(value: datetime, sep: str = "T") -> str:
    """ISO-format a datetime in the display timezone (e.g. +07:00)."""
    return to_display(value).isoformat(sep=sep)


def display_now() -> datetime:
    """Current time expressed in the display timezone."""
    return datetime.now(display_tz())
