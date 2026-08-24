"""RED tests for the Core-owned governed coding contract (AD-L5-05)."""
from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.orchestration.coding_governance import (
    CodingAssignment,
    CodingResultContract,
    FailureClassification,
    GovernanceContractError,
    ReviewerOutcome,
    validate_coding_completion,
)


def _assignment(tmp_path: Path) -> CodingAssignment:
    workspace = tmp_path / "anh-duong-core.worktrees" / "assignment-1"
    workspace.mkdir(parents=True)
    (workspace / ".git").write_text(
        "gitdir: /home/thadc/AIOS/anh-duong-core/.git/worktrees/assignment-1\n",
        encoding="utf-8",
    )
    return CodingAssignment(
        checkpoint_id="AD-L5-05",
        correlation_id="req_coding_1",
        workspace=str(workspace),
        manifest_digest="a" * 64,
        allowed_paths=("app/", "tests/"),
        reviewer_required=True,
        approval_required=False,
        max_semantic_repair_rounds=2,
    )


def _result() -> CodingResultContract:
    return CodingResultContract(
        checkpoint_id="AD-L5-05",
        correlation_id="req_coding_1",
        status="MERGE_READY",
        classification=FailureClassification.DELTA_FAILURE,
        manifest_digest="a" * 64,
        files_changed=("app/example.py", "tests/test_example.py"),
        commands_run=("pytest -q",),
        tests=({"name": "pytest", "status": "PASS"},),
        model="router/model",
        provider="router",
        profile="CE-2",
        duration_ms=100,
        error_code=None,
        production_write=False,
        service_restart=False,
        database_write=False,
        reviewer_outcome=ReviewerOutcome.PASS,
        reviewer_read_only=True,
        approval_granted=False,
        repair_round=0,
    )


def test_coding_assignment_rejects_production_workspace() -> None:
    with pytest.raises(ValidationError, match="isolated worktree"):
        CodingAssignment(
            checkpoint_id="AD-L5-05",
            correlation_id="req_coding_1",
            workspace="/home/thadc/AIOS/anh-duong-core",
            manifest_digest="a" * 64,
            allowed_paths=("app/",),
            reviewer_required=True,
            approval_required=False,
            max_semantic_repair_rounds=2,
        )


def test_coding_assignment_requires_isolated_worktree(tmp_path: Path) -> None:
    workspace = tmp_path / "ordinary-project"
    workspace.mkdir()
    assignment = CodingAssignment(
        checkpoint_id="AD-L5-05",
        correlation_id="req_coding_1",
        workspace=str(workspace),
        manifest_digest="a" * 64,
        allowed_paths=("app/",),
        reviewer_required=True,
        approval_required=False,
        max_semantic_repair_rounds=2,
    )

    with pytest.raises(GovernanceContractError, match="isolated"):
        assignment.validate_workspace()


def test_governed_completion_preserves_all_ce_fields_and_is_merge_ready(
    tmp_path: Path,
) -> None:
    assignment = _assignment(tmp_path)
    result = _result()

    validated = validate_coding_completion(assignment, result)

    assert validated.status == "MERGE_READY"
    assert validated.files_changed == ("app/example.py", "tests/test_example.py")
    assert validated.commands_run == ("pytest -q",)
    assert validated.tests == ({"name": "pytest", "status": "PASS"},)
    assert validated.model == "router/model"
    assert validated.provider == "router"
    assert validated.profile == "CE-2"
    assert validated.duration_ms == 100
    assert validated.error_code is None


@pytest.mark.parametrize(
    "override",
    (
        {"status": "completed"},
        {"reviewer_outcome": ReviewerOutcome.FAIL},
        {"reviewer_read_only": False},
        {"production_write": True},
        {"files_changed": ("README.md",)},
        {"checkpoint_id": "AD-L5-06"},
    ),
)
def test_coding_completion_fails_closed_without_required_governance_gates(
    tmp_path: Path,
    override: dict[str, object],
) -> None:
    assignment = _assignment(tmp_path)
    result = _result().model_copy(update=override)

    with pytest.raises(GovernanceContractError):
        validate_coding_completion(assignment, result)


@pytest.mark.parametrize(
    "classification, repair_round, allowed",
    (
        (FailureClassification.DELTA_FAILURE, 1, True),
        (FailureClassification.DELTA_FAILURE, 2, True),
        (FailureClassification.DELTA_FAILURE, 3, False),
        (FailureClassification.ENVIRONMENT_FAILURE, 1, False),
        (FailureClassification.PRE_EXISTING_FAILURE, 1, False),
    ),
)
def test_semantic_repair_is_limited_to_two_delta_rounds(
    classification: FailureClassification,
    repair_round: int,
    allowed: bool,
) -> None:
    result = _result().model_copy(
        update={
            "classification": classification,
            "repair_round": repair_round,
        }
    )

    if allowed:
        assert result.semantic_repair_allowed() is True
    else:
        assert result.semantic_repair_allowed() is False
