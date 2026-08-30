from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.capabilities.models import CapabilityKind


class PlanStatus(StrEnum):
    READY = "ready"
    BLOCKED = "blocked"


class PlanNodeKind(StrEnum):
    ACTION = "action"
    APPROVAL_GATE = "approval_gate"
    VERIFICATION_GATE = "verification_gate"


class PlanNodeState(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    BLOCKED = "blocked"
    FAILED = "failed"
    SKIPPED = "skipped"


class ExecutionBudget(BaseModel):
    model_config = ConfigDict(frozen=True)
    max_actions: int = Field(default=12, ge=1, le=128)
    max_elapsed_seconds: int = Field(default=1800, ge=1, le=86_400)
    actions_used: int = Field(default=0, ge=0)
    retries_used: int = Field(default=0, ge=0)
    started_at: datetime | None = None


class Goal(BaseModel):
    model_config = ConfigDict(frozen=True)
    statement: str = Field(min_length=1, max_length=20_000)
    project_id: str = Field(min_length=1, max_length=64)


class DefinitionOfDone(BaseModel):
    model_config = ConfigDict(frozen=True)
    criteria: tuple[str, ...] = Field(min_length=1)
    inferred: bool = False


class Constraint(BaseModel):
    model_config = ConfigDict(frozen=True)
    description: str = Field(min_length=1, max_length=2_000)
    source: str = Field(default="request", min_length=1, max_length=64)


class RiskBudget(BaseModel):
    model_config = ConfigDict(frozen=True)
    max_risk_level: int = Field(default=3, ge=0, le=4)
    max_plan_nodes: int = Field(default=12, ge=2, le=64)
    max_retries: int = Field(default=2, ge=0, le=10)
    max_replans: int = Field(default=3, ge=0, le=10)


class Deliverable(BaseModel):
    model_config = ConfigDict(frozen=True)
    description: str = Field(min_length=1, max_length=2_000)
    required: bool = True


class DecisionNeeded(BaseModel):
    model_config = ConfigDict(frozen=True)
    question: str = Field(min_length=1, max_length=2_000)
    reason: str = Field(min_length=1, max_length=2_000)


class VerificationRequirement(BaseModel):
    model_config = ConfigDict(frozen=True)
    description: str = Field(min_length=1, max_length=2_000)


class PlanningTruthSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)
    project_id: str
    project_version: int = Field(ge=1)
    project_status: str
    current_phase: str | None = None
    workspace: str | None = None
    workspace_exists: bool
    project_constraints: tuple[str, ...] = ()
    observed_at: datetime | None = None


class PlanningRequest(BaseModel):
    model_config = ConfigDict(frozen=True)
    request_id: str = Field(min_length=1, max_length=128)
    project_id: str = Field(min_length=1, max_length=64)
    outcome: str = Field(min_length=1, max_length=20_000)
    definition_of_done: DefinitionOfDone | None = None
    constraints: tuple[Constraint, ...] = ()
    risk_budget: RiskBudget = Field(default_factory=RiskBudget)
    deliverables: tuple[Deliverable, ...] = ()
    risk_level: int = Field(default=0, ge=0, le=4)
    approval_required: bool = False
    workspace: str | None = Field(default=None, max_length=1024)
    capability_requirements: tuple[CapabilityKind, ...] = (CapabilityKind.PLANNING,)


class PlanNodeExecution(BaseModel):
    model_config = ConfigDict(frozen=True)
    node_id: str = Field(min_length=1, max_length=64)
    state: PlanNodeState = PlanNodeState.PENDING
    attempts: int = Field(default=0, ge=0)
    evidence_ids: tuple[str, ...] = ()
    last_failure_class: str | None = Field(default=None, max_length=128)


class ExecutionEvidence(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: str = Field(min_length=1, max_length=128)
    node_id: str = Field(min_length=1, max_length=64)
    kind: str = Field(min_length=1, max_length=64)
    summary: str = Field(min_length=1, max_length=4_000)
    artifact_refs: tuple[str, ...] = ()
    verification_refs: tuple[str, ...] = ()
    external_run_id: str | None = Field(default=None, max_length=255)
    outcome: str | None = Field(default=None, max_length=32)
    criterion_verification: tuple[dict[str, object], ...] = ()
    result_payload: dict[str, object] | None = None
    provenance: str = Field(default="core", min_length=1, max_length=64)
    created_at: datetime | None = None


class PlanNode(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=255)
    kind: PlanNodeKind
    depends_on: tuple[str, ...] = ()
    capability_requirements: tuple[CapabilityKind, ...] = ()
    verification_requirements: tuple[VerificationRequirement, ...] = ()


class Plan(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: str = Field(min_length=1, max_length=128)
    revision: int = Field(default=1, ge=1)
    replanned_from_revision: int | None = Field(default=None, ge=1)
    replan_reason: str | None = Field(default=None, min_length=1, max_length=2_000)
    goal: Goal
    definition_of_done: DefinitionOfDone
    constraints: tuple[Constraint, ...]
    risk_budget: RiskBudget
    deliverables: tuple[Deliverable, ...]
    verification_requirements: tuple[VerificationRequirement, ...]
    truth: PlanningTruthSnapshot
    status: PlanStatus
    nodes: tuple[PlanNode, ...] = ()
    blocker: DecisionNeeded | None = None
    node_executions: tuple[PlanNodeExecution, ...] = ()
    evidence: tuple[ExecutionEvidence, ...] = ()
    execution_budget: ExecutionBudget = Field(default_factory=ExecutionBudget)
    outcome_judgement: dict[str, object] | None = None

    @model_validator(mode="after")
    def validate_graph_and_status(self) -> Plan:
        if self.status is PlanStatus.READY and self.blocker is not None:
            raise ValueError("ready plan cannot have a blocker")
        if self.status is PlanStatus.BLOCKED and self.blocker is None:
            raise ValueError("blocked plan requires exactly one blocker")
        if self.status is PlanStatus.BLOCKED and self.nodes:
            raise ValueError("blocked plan cannot contain executable nodes")
        if len(self.nodes) > self.risk_budget.max_plan_nodes:
            raise ValueError("plan exceeds max_plan_nodes")

        ids = [node.id for node in self.nodes]
        if len(ids) != len(set(ids)):
            raise ValueError("plan node ids must be unique")
        known = set(ids)
        for node in self.nodes:
            unknown = set(node.depends_on) - known
            if unknown:
                raise ValueError(f"unknown plan dependency: {sorted(unknown)}")

        graph = {node.id: node.depends_on for node in self.nodes}
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(node_id: str) -> None:
            if node_id in visiting:
                raise ValueError("plan dependency graph must be acyclic")
            if node_id in visited:
                return
            visiting.add(node_id)
            for dependency in graph[node_id]:
                visit(dependency)
            visiting.remove(node_id)
            visited.add(node_id)

        for node_id in graph:
            visit(node_id)

        if self.status is PlanStatus.READY:
            if not self.nodes:
                raise ValueError("ready plan requires nodes")
            if self.nodes[-1].kind is not PlanNodeKind.VERIFICATION_GATE:
                raise ValueError("ready plan must end with a verification gate")
        return self
