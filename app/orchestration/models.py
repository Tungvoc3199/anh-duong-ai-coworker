from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from app.capabilities.models import CapabilityDecision
from app.context_builder.models import ContextBundle
from app.policy import DecisionKind, RiskLevel
from app.routing.models import RouteDecision


class CoreRequest(BaseModel):
    """Immutable natural-language request accepted by the Core pipeline."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str = Field(max_length=20_000)
    request_id: str | None = Field(default=None, max_length=128)
    channel: str = Field(default="internal", max_length=64)
    actor: str = Field(default="internal", max_length=128)
    project_id: str | None = Field(default=None, max_length=64)
    task_id: str | None = Field(default=None, max_length=64)
    memory_scope_id: str | None = Field(default=None, max_length=128)
    source_chat_id: str | None = Field(default=None, max_length=128)
    source_session_id: str | None = Field(default=None, max_length=128)
    source_message_id: str | None = Field(default=None, max_length=128)

    @field_validator("text")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("text cannot be blank")
        return normalized

    @field_validator(
        "request_id",
        "project_id",
        "task_id",
        "memory_scope_id",
        "source_chat_id",
        "source_session_id",
        "source_message_id",
    )
    @classmethod
    def normalize_optional_identifier(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("identifier cannot be blank")
        return normalized

    @field_validator("channel", "actor")
    @classmethod
    def normalize_required_identifier(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("value cannot be blank")
        return normalized


class PersonaReference(BaseModel):
    """Audit-safe reference to the Persona used during preparation."""

    model_config = ConfigDict(frozen=True)

    version: str = Field(min_length=1)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class RequestProvenance(BaseModel):
    """Stable references explaining how a request was prepared."""

    model_config = ConfigDict(frozen=True)

    persona_version: str = Field(min_length=1)
    persona_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    route_rule_id: str = Field(min_length=1)
    capability_reason_code: str = Field(min_length=1)
    project_version: int | None = Field(default=None, ge=1)
    task_version: int | None = Field(default=None, ge=1)
    context_source_refs: tuple[str, ...] = ()


class WorkflowEnvelope(BaseModel):
    """Core-authoritative mapping for one durable async submission."""

    model_config = ConfigDict(frozen=True)

    project_id: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=255)
    goal: str = Field(min_length=1, max_length=20_000)
    mode: Literal["quick", "build"]
    priority: Literal["low", "normal", "high", "critical"]
    risk_level: RiskLevel
    approval_required: bool
    workspace: str | None = Field(default=None, max_length=1024)
    requested_by: str = Field(min_length=1, max_length=128)
    source_channel: str = Field(min_length=1, max_length=64)
    source_chat_id: str | None = Field(default=None, max_length=128)
    source_session_id: str | None = Field(default=None, max_length=128)
    source_message_id: str | None = Field(default=None, max_length=128)
    idempotency_key: str | None = Field(default=None, max_length=255)
    correlation_id: str = Field(min_length=1, max_length=128)
    constraints: tuple[str, ...] = ()
    policy_decision: DecisionKind
    policy_rule_id: str = Field(min_length=1, max_length=128)
    policy_reason: str = Field(min_length=1, max_length=2000)


class PreparedRequest(BaseModel):
    """Immutable, side-effect-free output of the Core request pipeline."""

    model_config = ConfigDict(frozen=True)

    request_id: str = Field(min_length=1, max_length=128)
    normalized_text: str = Field(min_length=1, max_length=20_000)
    persona: PersonaReference
    route_decision: RouteDecision
    capability_decision: CapabilityDecision
    context: ContextBundle
    project_id: str | None = None
    task_id: str | None = None
    execution_required: bool
    workflow: WorkflowEnvelope | None = None
    warnings: tuple[str, ...] = ()
    provenance: RequestProvenance
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def normalize_created_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def require_consistent_workflow(self) -> PreparedRequest:
        is_workflow = self.route_decision.route.value == "workflow"
        if self.execution_required != is_workflow:
            raise ValueError("execution_required must match workflow route")
        if self.execution_required != (self.workflow is not None):
            raise ValueError("workflow envelope must match execution_required")
        return self
