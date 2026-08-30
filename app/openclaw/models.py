from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator


class OpenClawChecklistItem(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    step: int = Field(ge=1)
    name: str
    check: str
    readonly_rule: str


class OpenClawWorkflowArtifacts(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    checklist: tuple[OpenClawChecklistItem, ...]


class OpenClawWorkflowVerification(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    method: str
    commands_run: int = Field(ge=0)
    files_changed: int = Field(ge=0)
    config_changed: bool
    services_restarted: bool
    notes: str


class CriterionVerification(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    criterion: str = Field(min_length=1, max_length=2_000)
    status: Literal["verified", "unmet", "unknown"]
    evidence_refs: tuple[str, ...] = ()
    explanation: str | None = Field(default=None, max_length=4_000)


class OpenClawExecutionRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    task_id: str
    run_id: str
    attempt: int = Field(ge=1)
    idempotency_key: str
    project_id: str
    goal: str
    mode: Literal["quick", "build"]
    workspace: str | None = None
    constraints: tuple[str, ...] = ()
    plan_node_id: str | None = Field(default=None, max_length=64)
    plan_node_title: str | None = Field(default=None, max_length=255)
    capability_requirements: tuple[str, ...] = ()
    dod_criteria: tuple[str, ...] = ()
    verification_requirements: tuple[str, ...] = ()
    prior_evidence: tuple[str, ...] = ()
    remaining_budget: dict[str, int] = Field(default_factory=dict)


class GovernanceResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    decision: Literal["allow", "require_approval", "deny", "escalate"]
    status: Literal["verified", "pending", "approved", "denied", "failed"]
    reason: str
    checkpoint_id: str | None = None
    correlation_id: str | None = None
    files_changed: tuple[str, ...] = ()
    commands_run: tuple[str, ...] = ()
    tests: tuple[dict[str, Any], ...] = ()
    production_write: bool = False
    database_write: bool = False
    service_restart: bool = False


class OpenClawExecutionResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    outcome: Literal["completed", "blocked", "failed"]
    summary: str
    governance_result: GovernanceResult | None = None
    criterion_verification: tuple[CriterionVerification, ...] = ()
    artifacts: tuple[str, ...] | OpenClawWorkflowArtifacts | dict[str, Any] = ()
    verification: tuple[str, ...] | OpenClawWorkflowVerification | dict[str, Any] = ()
    files_changed: tuple[str, ...] = ()
    commands_run: tuple[str, ...] = ()
    tests: tuple[dict[str, Any], ...] = ()
    model: str | None = None
    provider: str | None = None
    profile: str | None = None
    duration_ms: int | None = Field(default=None, ge=0)
    error_code: str | None = None
    external_run_id: str | None = None

    @field_validator("artifacts", mode="before")
    @classmethod
    def _validate_known_artifacts(
        cls,
        value: object,
    ) -> object:
        if isinstance(value, dict) and "checklist" in value:
            try:
                return OpenClawWorkflowArtifacts.model_validate(value)
            except ValidationError:
                return value
        return value

    @field_validator("verification", mode="before")
    @classmethod
    def _validate_known_verification(
        cls,
        value: object,
    ) -> object:
        required_keys = {
            "method",
            "commands_run",
            "files_changed",
            "config_changed",
            "services_restarted",
            "notes",
        }
        if isinstance(value, dict) and required_keys.issubset(value):
            try:
                return OpenClawWorkflowVerification.model_validate(value)
            except ValidationError:
                return value
        return value


class OpenClawTransportError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool,
        uncertain_side_effect: bool = False,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.uncertain_side_effect = uncertain_side_effect
        self.status_code = status_code
