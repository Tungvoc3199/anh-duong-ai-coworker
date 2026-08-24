"""Pure Core governance contracts for isolated coding assignments.

This module deliberately has no dependency on ADE-OS, Git subprocesses, or
OpenClaw.  It validates durable metadata supplied through Core-owned flows.
"""
from __future__ import annotations

import hashlib
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator


class GovernanceContractError(ValueError):
    """Raised when a governed coding invariant is not satisfied."""


class FailureClassification(StrEnum):
    DELTA_FAILURE = "DELTA_FAILURE"
    PRE_EXISTING_FAILURE = "PRE_EXISTING_FAILURE"
    ENVIRONMENT_FAILURE = "ENVIRONMENT_FAILURE"
    SCOPE_FAILURE = "SCOPE_FAILURE"
    GOVERNANCE_FAILURE = "GOVERNANCE_FAILURE"


class ReviewerOutcome(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    BLOCKED = "BLOCKED"


class CodingAssignment(BaseModel):
    """Core-authoritative identity and bounds for one coding execution."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    checkpoint_id: str = Field(min_length=1, max_length=128)
    correlation_id: str = Field(min_length=1, max_length=128)
    workspace: str = Field(min_length=1, max_length=1024)
    manifest_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    allowed_paths: tuple[str, ...] = Field(min_length=1)
    reviewer_required: bool
    approval_required: bool
    max_semantic_repair_rounds: int = Field(ge=0, le=2)

    @field_validator("workspace")
    @classmethod
    def require_nonproduction_workspace(cls, value: str) -> str:
        resolved = Path(value).resolve(strict=False)
        if resolved in {
            Path("/home/thadc/AIOS/anh-duong-core"),
            Path("/workspaces/anh-duong-core"),
        }:
            raise ValueError("workspace must be an isolated worktree")
        return str(resolved)

    @field_validator("allowed_paths")
    @classmethod
    def validate_allowed_paths(
        cls,
        values: tuple[str, ...],
    ) -> tuple[str, ...]:
        for value in values:
            path = Path(value)
            if path.is_absolute() or ".." in path.parts or not value:
                raise ValueError("allowed paths must be repository-relative")
        return values

    def validate_workspace(self) -> None:
        workspace = Path(self.workspace)
        try:
            git_file = (workspace / ".git").read_text(encoding="utf-8")
        except OSError as error:
            raise GovernanceContractError(
                "coding workspace is not an isolated worktree"
            ) from error
        if ".git/worktrees/" not in git_file:
            raise GovernanceContractError(
                "coding workspace has invalid worktree identity"
            )


def build_coding_assignment(
    *,
    checkpoint_id: str,
    correlation_id: str,
    project_workspace: str,
    constraints: tuple[str, ...],
    approval_required: bool,
) -> CodingAssignment:
    """Create the Core-authoritative governed assignment for a code operation."""
    project_path = Path(project_workspace).resolve(strict=False)
    worktree_root = project_path.parent / f"{project_path.name}.worktrees"
    workspace = worktree_root / checkpoint_id.casefold().replace("_", "-")
    manifest_payload = {
        "checkpoint_id": checkpoint_id,
        "correlation_id": correlation_id,
        "workspace": str(workspace),
        "constraints": sorted(constraints),
    }
    manifest_digest = hashlib.sha256(
        repr(manifest_payload).encode("utf-8")
    ).hexdigest()
    return CodingAssignment(
        checkpoint_id=checkpoint_id,
        correlation_id=correlation_id,
        workspace=str(workspace),
        manifest_digest=manifest_digest,
        allowed_paths=("app/", "tests/", "docs/", "scripts/"),
        reviewer_required=True,
        approval_required=approval_required,
        max_semantic_repair_rounds=2,
    )


class CodingResultContract(BaseModel):
    """Structured CE result required before a coding run may complete."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    checkpoint_id: str = Field(min_length=1, max_length=128)
    correlation_id: str = Field(min_length=1, max_length=128)
    status: str = Field(min_length=1, max_length=64)
    classification: FailureClassification
    manifest_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    files_changed: tuple[str, ...]
    commands_run: tuple[str, ...]
    tests: tuple[dict[str, object], ...]
    model: str | None
    provider: str | None
    profile: str | None
    duration_ms: int | None = Field(default=None, ge=0)
    error_code: str | None
    production_write: bool
    service_restart: bool
    database_write: bool
    reviewer_outcome: ReviewerOutcome
    reviewer_read_only: bool
    approval_granted: bool
    repair_round: int = Field(ge=0)

    def semantic_repair_allowed(self) -> bool:
        return (
            self.classification is FailureClassification.DELTA_FAILURE
            and 1 <= self.repair_round <= 2
        )


def validate_coding_completion(
    assignment: CodingAssignment,
    result: CodingResultContract,
) -> CodingResultContract:
    """Fail closed unless the final coding result is safe and merge-ready."""
    assignment.validate_workspace()
    if result.checkpoint_id != assignment.checkpoint_id:
        raise GovernanceContractError("checkpoint identity does not match")
    if result.correlation_id != assignment.correlation_id:
        raise GovernanceContractError("correlation identity does not match")
    if result.manifest_digest != assignment.manifest_digest:
        raise GovernanceContractError("manifest identity does not match")
    if result.status != "MERGE_READY":
        raise GovernanceContractError("coding result is not merge ready")
    if result.production_write or result.service_restart or result.database_write:
        raise GovernanceContractError("coding result reports forbidden side effect")
    if assignment.reviewer_required and (
        result.reviewer_outcome is not ReviewerOutcome.PASS
        or not result.reviewer_read_only
    ):
        raise GovernanceContractError("read-only reviewer did not pass")
    if assignment.approval_required and not result.approval_granted:
        raise GovernanceContractError("required approval is absent")
    for changed in result.files_changed:
        path = Path(changed)
        if path.is_absolute() or ".." in path.parts or not any(
            changed == allowed.rstrip("/")
            or changed.startswith(f"{allowed.rstrip('/')}/")
            for allowed in assignment.allowed_paths
        ):
            raise GovernanceContractError("changed path is outside assignment scope")
    return result
