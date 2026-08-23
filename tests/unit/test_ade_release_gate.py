"""Focused tests for ADE-OS release gate enforcement."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from ade_os import core  # noqa: E402


def test_release_without_all_gates_not_release_ready() -> None:
    result = core.evaluate_release_gate({"tests": True, "review": "PASS"}, approved=False)
    assert result["release_ready"] is False
    assert result["performed_release"] is False


def test_release_gate_never_performs_release() -> None:
    evidence = {
        "conflict_gate": True,
        "scoped_diff": True,
        "tests": True,
        "backup": True,
        "rollback": True,
        "runtime_e2e": True,
        "review": "PASS",
    }
    result = core.evaluate_release_gate(evidence, approved=True)
    assert result["performed_release"] is False


def test_release_gate_evaluates_readiness_with_all_gates() -> None:
    evidence = {
        "conflict_gate": True,
        "scoped_diff": True,
        "tests": True,
        "backup": True,
        "rollback": True,
        "runtime_e2e": True,
        "review": "PASS",
    }
    result = core.evaluate_release_gate(evidence, approved=True)
    assert result["release_ready"] is True


def test_release_gate_missing_approval_not_ready() -> None:
    evidence = {
        "conflict_gate": True,
        "scoped_diff": True,
        "tests": True,
        "backup": True,
        "rollback": True,
        "runtime_e2e": True,
        "review": "PASS",
    }
    result = core.evaluate_release_gate(evidence, approved=False)
    assert result["release_ready"] is False


def test_release_gate_missing_review_not_ready() -> None:
    evidence = {
        "conflict_gate": True,
        "scoped_diff": True,
        "tests": True,
        "backup": True,
        "rollback": True,
        "runtime_e2e": True,
    }
    result = core.evaluate_release_gate(evidence, approved=True)
    assert result["release_ready"] is False
