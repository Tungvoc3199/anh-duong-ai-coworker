"""PreToolUse governance hook tests for AD-L5-01."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GUARD = ROOT / "scripts/agent/pretool_guard.py"


def run_guard(payload: dict[str, object]) -> dict[str, object]:
    result = subprocess.run(
        [sys.executable, str(GUARD)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        cwd=ROOT,
        check=True,
    )
    return json.loads(result.stdout)["hookSpecificOutput"]


def test_pretool_denies_production_core_writable_workspace() -> None:
    output = run_guard(
        {
            "tool_input": "edit file",
            "ade_governance": {
                "workspace": "/home/thadc/AIOS/anh-duong-core",
                "writable": True,
            },
        }
    )
    assert output["permissionDecision"] == "deny"
    assert "GOVERNANCE_FAILURE" in output["permissionDecisionReason"]


def test_pretool_denies_plain_write_payload_to_production_core() -> None:
    output = run_guard(
        {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/home/thadc/AIOS/anh-duong-core/scripts/ade_os/core.py",
                "content": "change",
            },
        }
    )
    assert output["permissionDecision"] == "deny"
    assert "GOVERNANCE_FAILURE" in output["permissionDecisionReason"]


def test_pretool_denies_plain_write_payload_to_container_core() -> None:
    output = run_guard(
        {
            "tool_name": "Edit",
            "tool_input": {
                "file_path": "/workspaces/anh-duong-core/scripts/ade_os/core.py",
                "old_string": "a",
                "new_string": "b",
            },
        }
    )
    assert output["permissionDecision"] == "deny"
    assert "GOVERNANCE_FAILURE" in output["permissionDecisionReason"]


def test_pretool_denies_scope_escape() -> None:
    output = run_guard(
        {
            "tool_input": "edit file",
            "ade_governance": {
                "changed_paths": ["app/main.py"],
                "allowed_paths": ["scripts/ade_os.py"],
            },
        }
    )
    assert output["permissionDecision"] == "deny"
    assert "SCOPE_VIOLATION" in output["permissionDecisionReason"]


def test_pretool_plain_write_payload_without_allowed_paths_fails_closed() -> None:
    output = run_guard(
        {
            "tool_name": "Write",
            "tool_input": {
                "file_path": str(ROOT / "app/main.py"),
                "content": "change",
            },
        }
    )
    assert output["permissionDecision"] == "deny"
    assert "SCOPE_VIOLATION" in output["permissionDecisionReason"]


def test_pretool_allows_write_to_worktree_root_policy_test() -> None:
    output = run_guard(
        {
            "tool_name": "Write",
            "tool_input": {
                "file_path": str(ROOT / "tests/unit/test_ade_worktree_root_policy.py"),
                "content": "change",
            },
        }
    )
    assert output["permissionDecision"] == "allow"


def test_pretool_denies_descendant_beneath_exact_policy_test_path() -> None:
    output = run_guard(
        {
            "tool_name": "Write",
            "tool_input": {
                "file_path": str(
                    ROOT / "tests/unit/test_ade_worktree_root_policy.py/unexpected.py"
                ),
                "content": "change",
            },
        }
    )
    assert output["permissionDecision"] == "deny"
    assert "SCOPE_VIOLATION" in output["permissionDecisionReason"]


def test_pretool_write_tool_without_path_fails_closed() -> None:
    output = run_guard(
        {
            "tool_name": "Write",
            "tool_input": {
                "content": "change",
            },
        }
    )
    assert output["permissionDecision"] == "deny"
    assert "SCOPE_VIOLATION" in output["permissionDecisionReason"]


def test_pretool_denies_reviewer_write() -> None:
    output = run_guard(
        {
            "tool_input": "edit file",
            "ade_governance": {
                "role": "reviewer",
                "capability": "write",
            },
        }
    )
    assert output["permissionDecision"] == "deny"
    assert "GOVERNANCE_FAILURE" in output["permissionDecisionReason"]


def test_pretool_denies_semantic_repair_for_environment_failure() -> None:
    output = run_guard(
        {
            "tool_input": "repair",
            "ade_governance": {
                "failure_class": "ENVIRONMENT_FAILURE",
                "repair_round": 1,
                "max_rounds": 2,
            },
        }
    )
    assert output["permissionDecision"] == "deny"
    assert "GOVERNANCE_FAILURE" in output["permissionDecisionReason"]
