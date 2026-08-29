from __future__ import annotations

from enum import StrEnum

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    computed_field,
    field_validator,
    model_validator,
)

from app.capabilities.models import CapabilityDecision
from app.persona.models import PersonaSnapshot
from app.policy import DecisionKind, RiskLevel
from app.routing.models import RouteDecision


class ContextSectionKind(StrEnum):
    PERSONA = "persona"
    ROUTING_DECISIONS = "routing_decisions"
    PROJECT_CONTEXT = "project_context"
    ACTIVE_TASK = "active_task"
    RELEVANT_MEMORY = "relevant_memory"
    CURRENT_REQUEST = "current_request"


class ContextTokenBudget(BaseModel):
    """First-class estimated-token budget for one context build."""

    model_config = ConfigDict(frozen=True)

    context_window_tokens: int = Field(default=16_000, gt=0)
    response_reserve_tokens: int = Field(default=3_000, ge=0)
    runtime_reserve_tokens: int = Field(default=1_000, ge=0)
    persona_soft_tokens: int = Field(default=1_200, ge=0)
    routing_soft_tokens: int = Field(default=800, ge=0)
    task_soft_tokens: int = Field(default=3_200, ge=0)
    project_soft_tokens: int = Field(default=2_400, ge=0)
    memory_soft_tokens: int = Field(default=4_400, ge=0)
    selection_enabled: bool = Field(default=True)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def usable_context_tokens(self) -> int:
        return (
            self.context_window_tokens - self.response_reserve_tokens - self.runtime_reserve_tokens
        )

    @model_validator(mode="after")
    def validate_usable_context(self) -> ContextTokenBudget:
        if self.usable_context_tokens <= 0:
            raise ValueError("usable_context_tokens must be greater than 0")
        return self


class ProjectContextSnapshot(BaseModel):
    """Read-only project facts supplied by the current application flow."""

    model_config = ConfigDict(frozen=True)

    identity: str = Field(min_length=1)
    goal: str | None = None
    current_phase: str | None = None
    architecture_constraints: tuple[str, ...] = ()
    decisions: tuple[str, ...] = ()
    status: str | None = None
    history: tuple[str, ...] = ()


class TaskContextSnapshot(BaseModel):
    """Read-only active-task facts without introducing persistence."""

    model_config = ConfigDict(frozen=True)

    identity: str = Field(min_length=1)
    active_goal: str = Field(min_length=1)
    status: str | None = None
    constraints: tuple[str, ...] = ()
    acceptance_criteria: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()
    next_action: str | None = None
    history: tuple[str, ...] = ()


class RuntimePolicySnapshot(BaseModel):
    """Effective workflow policy facts computed by the runtime."""

    model_config = ConfigDict(frozen=True)

    risk_level: RiskLevel
    approval_required: bool
    policy_decision: DecisionKind
    policy_rule_id: str = Field(min_length=1, max_length=128)
    policy_reason: str = Field(min_length=1, max_length=2000)


class ContextBuildRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    current_request: str
    persona: PersonaSnapshot
    fast_router_decision: RouteDecision
    capability_decision: CapabilityDecision
    project_context: ProjectContextSnapshot | None = None
    task_context: TaskContextSnapshot | None = None
    runtime_policy: RuntimePolicySnapshot | None = None
    token_budget: ContextTokenBudget = Field(default_factory=ContextTokenBudget)
    memory_scope_id: str | None = None

    @field_validator("current_request")
    @classmethod
    def validate_current_request(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("current_request cannot be blank")
        return normalized


class ContextSection(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: ContextSectionKind
    content: str
    priority: int = Field(ge=0)
    estimated_tokens: int = Field(ge=0)
    source_refs: tuple[str, ...]
    truncated: bool = False


class ContextItemChange(BaseModel):
    model_config = ConfigDict(frozen=True)

    section: ContextSectionKind
    source_ref: str
    reason: str
    original_estimated_tokens: int = Field(ge=0)
    final_estimated_tokens: int = Field(ge=0)


class ContextProvenance(BaseModel):
    model_config = ConfigDict(frozen=True)

    section: ContextSectionKind
    source_refs: tuple[str, ...]


class ContextBudgetMetrics(BaseModel):
    """Pure in-process, secret-safe reduction observability."""

    model_config = ConfigDict(frozen=True)

    candidate_estimated_tokens: int = Field(default=0, ge=0)
    selected_estimated_tokens: int = Field(default=0, ge=0)
    dropped_estimated_tokens: int = Field(default=0, ge=0)
    reduction_pct: float = Field(default=0.0, ge=0.0, le=1.0)
    tokens_by_section: dict[ContextSectionKind, int] = Field(default_factory=dict)
    dropped_by_reason: dict[str, int] = Field(default_factory=dict)


class ContextBundle(BaseModel):
    model_config = ConfigDict(frozen=True)

    sections: tuple[ContextSection, ...]
    rendered_context: str
    token_budget: ContextTokenBudget
    estimated_tokens: int = Field(ge=0)
    remaining_tokens: int = Field(ge=0)
    dropped_items: tuple[ContextItemChange, ...] = ()
    truncated_items: tuple[ContextItemChange, ...] = ()
    warnings: tuple[str, ...] = ()
    provenance: tuple[ContextProvenance, ...] = ()
    candidate_estimated_tokens: int = Field(default=0, ge=0)
    dropped_estimated_tokens: int = Field(default=0, ge=0)
    reduction_pct: float = Field(default=0.0, ge=0.0, le=1.0)
    tokens_by_section: dict[ContextSectionKind, int] = Field(default_factory=dict)
    dropped_by_reason: dict[str, int] = Field(default_factory=dict)


class ContextBudgetExceededError(ValueError):
    """Raised when required context alone cannot fit the usable budget."""

    def __init__(self, required_tokens: int, usable_tokens: int) -> None:
        self.required_tokens = required_tokens
        self.usable_tokens = usable_tokens
        super().__init__(
            "Required context exceeds usable token budget: "
            f"required={required_tokens}, usable={usable_tokens}"
        )
