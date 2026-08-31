from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict


class MetricSupport(StrEnum):
    AVAILABLE = "available"
    DERIVED = "derived"
    UNSUPPORTED = "unsupported"


class MetricDatum(BaseModel):
    model_config = ConfigDict(frozen=True)

    support: MetricSupport
    value: Any | None
    producer: str
    durable_source: str
    reason: str | None = None


class GoalTelemetry(BaseModel):
    model_config = ConfigDict(frozen=True)

    run_id: str
    task_id: str
    status: str
    metrics: dict[str, MetricDatum]


class SystemTelemetry(BaseModel):
    model_config = ConfigDict(frozen=True)

    population: dict[str, int]
    metrics: dict[str, MetricDatum]
