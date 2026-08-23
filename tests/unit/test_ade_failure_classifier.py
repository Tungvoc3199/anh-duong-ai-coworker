"""Focused tests for ADE-OS failure classification enforcement."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from ade_os import core  # noqa: E402


def test_failure_classes_are_exactly_five() -> None:
    assert core.FAILURE_CLASSES == (
        "DELTA_FAILURE",
        "PRE_EXISTING_FAILURE",
        "ENVIRONMENT_FAILURE",
        "SCOPE_FAILURE",
        "GOVERNANCE_FAILURE",
    )


def test_only_delta_failure_may_enter_semantic_repair() -> None:
    result = core.validate_semantic_repair("DELTA_FAILURE", repair_round=1, max_rounds=2)
    assert result["status"] == "ALLOW"


@pytest.mark.parametrize(
    "failure_class",
    ["PRE_EXISTING_FAILURE", "ENVIRONMENT_FAILURE", "SCOPE_FAILURE", "GOVERNANCE_FAILURE"],
)
def test_non_delta_failure_cannot_trigger_semantic_repair(failure_class: str) -> None:
    result = core.validate_semantic_repair(failure_class, repair_round=1, max_rounds=2)
    assert result["status"] == "DENY"
    assert result["reason"] == "GOVERNANCE_FAILURE"


def test_semantic_repair_max_two_blocked() -> None:
    result = core.validate_semantic_repair("DELTA_FAILURE", repair_round=3, max_rounds=2)
    assert result["status"] == "DENY"
    assert result["reason"] == "GOVERNANCE_FAILURE"


def test_semantic_repair_at_boundary_allowed() -> None:
    result = core.validate_semantic_repair("DELTA_FAILURE", repair_round=2, max_rounds=2)
    assert result["status"] == "ALLOW"


def test_unknown_failure_class_denied() -> None:
    result = core.validate_semantic_repair("UNKNOWN_CLASS", repair_round=1, max_rounds=2)
    assert result["status"] == "DENY"
