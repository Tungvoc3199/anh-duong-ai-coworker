from __future__ import annotations

from enum import IntEnum, StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class RiskLevel(IntEnum):
    """Risk levels locked by Design Specification v1.1."""

    READ_ONLY = 0
    SAFE_WRITE = 1
    SENSITIVE = 2
    HIGH_RISK = 3
    FORBIDDEN = 4


class DecisionKind(StrEnum):
    ALLOW = "allow"
    REQUIRE_APPROVAL = "require_approval"
    DENY = "deny"
    ESCALATE = "escalate"


class ApprovalScope(StrEnum):
    SINGLE_ACTION = "single_action"
    WORKFLOW = "workflow"
    SESSION = "session"


class PolicyAction(BaseModel):
    """Facts about an intended action before execution."""

    model_config = ConfigDict(frozen=True)

    name: str = Field(min_length=1, max_length=128)
    declared_risk_level: RiskLevel | None = None
    target_path: Path | None = None
    workspace_root: Path | None = None

    destructive: bool = False
    modifies_runtime: bool = False
    installs_dependencies: bool = False
    changes_schema: bool = False
    uses_quota: bool = False
    external_side_effect: bool = False
    sends_data_externally: bool = False
    incurs_cost: bool = False
    changes_permissions: bool = False
    deploys_or_publishes: bool = False

    bypasses_security: bool = False
    disables_audit: bool = False
    requests_self_approval: bool = False
    requests_privilege_escalation: bool = False
    exposes_secrets: bool = False

    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = value.strip().lower().replace("-", "_")
        if not normalized:
            raise ValueError("action name cannot be empty")
        return normalized


class PolicyDecision(BaseModel):
    """Immutable and auditable deterministic decision."""

    model_config = ConfigDict(frozen=True)

    kind: DecisionKind
    effective_risk_level: RiskLevel
    rule_id: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    approval_scope: ApprovalScope | None = None
    normalized_target_path: Path | None = None

    @property
    def requires_approval(self) -> bool:
        return self.kind is DecisionKind.REQUIRE_APPROVAL
