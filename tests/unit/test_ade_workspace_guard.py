"""PreToolUse governance hook tests for AD-L5-01."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GUARD = ROOT / "scripts/agent/pretool_guard.py"


def run_guard(
    payload: dict[str, object], *, env: dict[str, str] | None = None
) -> dict[str, object]:
    result = subprocess.run(
        [sys.executable, str(GUARD)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        cwd=ROOT,
        check=True,
        env=env,
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


def test_pretool_allows_write_to_worktree_root_policy_test(tmp_path: Path) -> None:
    env = _guard_env(
        tmp_path,
        {
            "checkpoint_id": "AD-BUG-X",
            "work_type": "repair",
            "status": "ACTIVE",
            "value_gate_status": "NOT_REQUIRED",
        },
    )
    output = run_guard(
        {
            "cwd": str(ROOT),
            "tool_name": "Write",
            "tool_input": {
                "file_path": str(ROOT / "tests/unit/test_ade_worktree_root_policy.py"),
                "content": "change",
            },
        },
        env=env,
    )
    assert output["permissionDecision"] == "allow"


def test_pretool_denies_descendant_beneath_exact_policy_test_path(tmp_path: Path) -> None:
    env = _guard_env(
        tmp_path,
        {
            "checkpoint_id": "AD-BUG-X",
            "work_type": "repair",
            "status": "ACTIVE",
            "value_gate_status": "NOT_REQUIRED",
        },
    )
    output = run_guard(
        {
            "cwd": str(ROOT),
            "tool_name": "Write",
            "tool_input": {
                "file_path": str(
                    ROOT / "tests/unit/test_ade_worktree_root_policy.py/unexpected.py"
                ),
                "content": "change",
            },
        },
        env=env,
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


def _guard_env(tmp_path: Path, item: dict[str, object] | None = None) -> dict[str, str]:
    home = tmp_path / "home"
    if item is not None:
        digest = hashlib.sha256(str(ROOT.resolve()).encode()).hexdigest()[:16]
        state = home / ".local/state/ade-os" / digest / "active-checkpoint.json"
        state.parent.mkdir(parents=True, exist_ok=True)
        state.write_text(
            json.dumps({"version": 1, "updated_at": "test", "items": [item]}),
            encoding="utf-8",
        )
    return {**os.environ, "HOME": str(home)}


def test_pretool_denies_write_without_active_checkpoint(tmp_path: Path) -> None:
    output = run_guard(
        {
            "cwd": str(ROOT),
            "tool_name": "Write",
            "tool_input": {"file_path": "scripts/ade_os.py", "content": "change"},
        },
        env=_guard_env(tmp_path),
    )
    assert output["permissionDecision"] == "deny"
    assert "ACTIVE_CHECKPOINT_REQUIRED" in output["permissionDecisionReason"]


def test_pretool_denies_feature_checkpoint_without_allowed_value_gate(tmp_path: Path) -> None:
    env = _guard_env(
        tmp_path,
        {
            "checkpoint_id": "AD-FEATURE-X",
            "work_type": "feature",
            "status": "ACTIVE",
            "value_gate_status": "DENY",
        },
    )
    output = run_guard(
        {
            "cwd": str(ROOT),
            "tool_name": "Write",
            "tool_input": {"file_path": "scripts/ade_os.py", "content": "change"},
        },
        env=env,
    )
    assert output["permissionDecision"] == "deny"
    assert "VALUE_GATE_REQUIRED" in output["permissionDecisionReason"]


def test_pretool_denies_terminal_mutation_without_active_checkpoint(tmp_path: Path) -> None:
    output = run_guard(
        {
            "cwd": str(ROOT),
            "tool_name": "run_in_terminal",
            "tool_input": {"command": "python3 -c \"open('x','w').write('x')\""},
        },
        env=_guard_env(tmp_path),
    )
    assert output["permissionDecision"] == "deny"
    assert "ACTIVE_CHECKPOINT_REQUIRED" in output["permissionDecisionReason"]


def test_pretool_allows_checkpoint_start_bootstrap_without_active_checkpoint(
    tmp_path: Path,
) -> None:
    output = run_guard(
        {
            "cwd": str(ROOT),
            "tool_name": "run_in_terminal",
            "tool_input": {
                "command": (
                    "python3 scripts/ade_os.py checkpoint start --evidence "
                    "/mnt/f/AIOS/anh-duong-checkpoints/AD-X/start.json"
                )
            },
        },
        env=_guard_env(tmp_path),
    )
    assert output["permissionDecision"] == "allow"


def test_pretool_allows_read_only_terminal_without_active_checkpoint(tmp_path: Path) -> None:
    output = run_guard(
        {
            "cwd": str(ROOT),
            "tool_name": "run_in_terminal",
            "tool_input": {"command": "git status --short"},
        },
        env=_guard_env(tmp_path),
    )
    assert output["permissionDecision"] == "allow"


def test_pretool_allows_start_evidence_artifact_write_without_active_checkpoint(
    tmp_path: Path,
) -> None:
    output = run_guard(
        {
            "cwd": str(ROOT),
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/mnt/f/AIOS/anh-duong-checkpoints/AD-X/start.json",
                "content": "{}",
            },
        },
        env=_guard_env(tmp_path),
    )
    assert output["permissionDecision"] == "allow"


def test_pretool_allows_write_with_active_repair_checkpoint(tmp_path: Path) -> None:
    env = _guard_env(
        tmp_path,
        {
            "checkpoint_id": "AD-BUG-X",
            "work_type": "repair",
            "status": "ACTIVE",
            "value_gate_status": "NOT_REQUIRED",
        },
    )
    output = run_guard(
        {
            "cwd": str(ROOT),
            "tool_name": "Write",
            "tool_input": {"file_path": "scripts/ade_os.py", "content": "change"},
        },
        env=env,
    )
    assert output["permissionDecision"] == "allow"


def test_pretool_allows_feature_with_allowed_value_gate(tmp_path: Path) -> None:
    env = _guard_env(
        tmp_path,
        {
            "checkpoint_id": "AD-FEATURE-X",
            "work_type": "feature",
            "status": "ACTIVE",
            "value_gate_status": "ALLOW",
        },
    )
    output = run_guard(
        {
            "cwd": str(ROOT),
            "tool_name": "Write",
            "tool_input": {"file_path": "scripts/ade_os.py", "content": "change"},
        },
        env=env,
    )
    assert output["permissionDecision"] == "allow"


def test_pretool_does_not_treat_find_delete_as_read_only(tmp_path: Path) -> None:
    output = run_guard(
        {
            "cwd": str(ROOT),
            "tool_name": "run_in_terminal",
            "tool_input": {"command": "find . -delete"},
        },
        env=_guard_env(tmp_path),
    )
    assert output["permissionDecision"] == "deny"
    assert "ACTIVE_CHECKPOINT_REQUIRED" in output["permissionDecisionReason"]


def test_pretool_does_not_treat_ruff_fix_as_read_only(tmp_path: Path) -> None:
    output = run_guard(
        {
            "cwd": str(ROOT),
            "tool_name": "run_in_terminal",
            "tool_input": {"command": "ruff check --fix ."},
        },
        env=_guard_env(tmp_path),
    )
    assert output["permissionDecision"] == "deny"
    assert "ACTIVE_CHECKPOINT_REQUIRED" in output["permissionDecisionReason"]


def test_pretool_does_not_treat_pytest_as_read_only(tmp_path: Path) -> None:
    output = run_guard(
        {
            "cwd": str(ROOT),
            "tool_name": "run_in_terminal",
            "tool_input": {"command": "python3 -m pytest -q"},
        },
        env=_guard_env(tmp_path),
    )
    assert output["permissionDecision"] == "deny"
    assert "ACTIVE_CHECKPOINT_REQUIRED" in output["permissionDecisionReason"]


def test_pretool_denies_overwriting_existing_bootstrap_artifact(tmp_path: Path) -> None:
    artifact = Path("/mnt/f/AIOS/anh-duong-checkpoints/AD-TEST-EXISTING/start.json")
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text("{}", encoding="utf-8")
    try:
        output = run_guard(
            {
                "cwd": str(ROOT),
                "tool_name": "Write",
                "tool_input": {"file_path": str(artifact), "content": "{}"},
            },
            env=_guard_env(tmp_path),
        )
        assert output["permissionDecision"] == "deny"
    finally:
        artifact.unlink(missing_ok=True)
        artifact.parent.rmdir()


def test_pretool_allows_direct_checkpoint_bootstrap_mkdir(tmp_path: Path) -> None:
    output = run_guard(
        {
            "cwd": str(ROOT),
            "tool_name": "run_in_terminal",
            "tool_input": {"command": "mkdir -p /mnt/f/AIOS/anh-duong-checkpoints/AD-NEW"},
        },
        env=_guard_env(tmp_path),
    )
    assert output["permissionDecision"] == "allow"


def test_pretool_denies_nested_bootstrap_mkdir(tmp_path: Path) -> None:
    output = run_guard(
        {
            "cwd": str(ROOT),
            "tool_name": "run_in_terminal",
            "tool_input": {"command": "mkdir -p /mnt/f/AIOS/anh-duong-checkpoints/AD-NEW/nested"},
        },
        env=_guard_env(tmp_path),
    )
    assert output["permissionDecision"] == "deny"


def test_pretool_actual_mutation_tool_names_require_checkpoint(tmp_path: Path) -> None:
    cases = [
        ("create_file", {"filePath": "scripts/ade_os.py", "content": "x"}),
        (
            "replace_string_in_file",
            {"filePath": "scripts/ade_os.py", "oldString": "a", "newString": "b"},
        ),
        ("insert_edit_into_file", {"filePath": "scripts/ade_os.py", "code": "x"}),
        ("multi_replace_string_in_file", {"replacements": [{"filePath": "scripts/ade_os.py"}]}),
        ("create_directory", {"dirPath": "docs/ade-os/new-dir"}),
        ("Bash", {"command": "python3 -c \"open('x','w').write('x')\""}),
        ("send_to_terminal", {"command": "rm x", "id": "1"}),
        ("create_and_run_task", {"task": {"type": "shell", "command": "touch x"}}),
    ]
    env = _guard_env(tmp_path)
    for name, tool_input in cases:
        output = run_guard({"cwd": str(ROOT), "tool_name": name, "tool_input": tool_input}, env=env)
        assert output["permissionDecision"] == "deny", name
        assert "ACTIVE_CHECKPOINT_REQUIRED" in output["permissionDecisionReason"], name


def test_pretool_checkpoint_start_bypass_requires_real_python_invocation(tmp_path: Path) -> None:
    output = run_guard(
        {
            "cwd": str(ROOT),
            "tool_name": "run_in_terminal",
            "tool_input": {
                "command": (
                    "rm scripts/ade_os.py checkpoint start --evidence "
                    "/mnt/f/AIOS/anh-duong-checkpoints/AD-X/start.json"
                )
            },
        },
        env=_guard_env(tmp_path),
    )
    assert output["permissionDecision"] == "deny"
    assert "ACTIVE_CHECKPOINT_REQUIRED" in output["permissionDecisionReason"]


def test_pretool_rejects_fake_checkpoint_start_executable_paths(tmp_path: Path) -> None:
    evidence = "/mnt/f/AIOS/anh-duong-checkpoints/AD-X/start.json"
    commands = (
        f"python3 /tmp/fake/scripts/ade_os.py checkpoint start --evidence {evidence}",
        f"/tmp/fake/scripts/ade_os.py checkpoint start --evidence {evidence}",
    )
    for command in commands:
        output = run_guard(
            {
                "cwd": str(ROOT),
                "tool_name": "run_in_terminal",
                "tool_input": {"command": command},
            },
            env=_guard_env(tmp_path),
        )
        assert output["permissionDecision"] == "deny", command
        assert "ACTIVE_CHECKPOINT_REQUIRED" in output["permissionDecisionReason"], command


def test_pretool_rejects_write_to_unregistered_worktree_lane(tmp_path: Path) -> None:
    env = _guard_env(
        tmp_path,
        {
            "checkpoint_id": "AD-BUG-X",
            "work_type": "repair",
            "status": "ACTIVE",
            "value_gate_status": "NOT_REQUIRED",
        },
    )
    output = run_guard(
        {
            "cwd": str(ROOT),
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/home/thadc/AIOS/worktrees/not-registered/scripts/ade_os.py",
                "content": "change",
            },
        },
        env=env,
    )
    assert output["permissionDecision"] == "deny"
    assert "GOVERNANCE_FAILURE" in output["permissionDecisionReason"]


def test_pretool_binds_active_checkpoint_to_target_worktree(tmp_path: Path) -> None:
    env = _guard_env(
        tmp_path,
        {
            "checkpoint_id": "AD-BUG-X",
            "work_type": "repair",
            "status": "ACTIVE",
            "value_gate_status": "NOT_REQUIRED",
        },
    )
    other = Path("/home/thadc/AIOS/worktrees/ad-roadmap-value-gate-1/scripts/ade_os.py")
    output = run_guard(
        {
            "cwd": str(ROOT),
            "tool_name": "Write",
            "tool_input": {"file_path": str(other), "content": "change"},
        },
        env=env,
    )
    assert output["permissionDecision"] == "deny"
    assert "WORKSPACE_MISMATCH" in output["permissionDecisionReason"]


def test_pretool_terminal_mutation_rejects_external_targets_and_state_forging(
    tmp_path: Path,
) -> None:
    env = _guard_env(
        tmp_path,
        {
            "checkpoint_id": "AD-BUG-X",
            "work_type": "repair",
            "status": "ACTIVE",
            "value_gate_status": "NOT_REQUIRED",
        },
    )
    digest = hashlib.sha256(str(ROOT.resolve()).encode()).hexdigest()[:16]
    state = tmp_path / "home/.local/state/ade-os" / digest / "active-checkpoint.json"
    commands = (
        "touch /home/thadc/AIOS/anh-duong-core/SHOULD_NOT_WRITE",
        "touch /workspaces/anh-duong-core/SHOULD_NOT_WRITE",
        "touch /home/thadc/AIOS/arbitrary/SHOULD_NOT_WRITE",
        f"python3 -c \"open('{state}','w').write('{{}}')\"",
    )
    for command in commands:
        output = run_guard(
            {
                "cwd": str(ROOT),
                "tool_name": "run_in_terminal",
                "tool_input": {"command": command},
            },
            env=env,
        )
        assert output["permissionDecision"] == "deny", command
        assert "WORKSPACE_SCOPE_FAILURE" in output["permissionDecisionReason"], command


def test_pretool_allows_terminal_mutation_inside_active_workspace(tmp_path: Path) -> None:
    env = _guard_env(
        tmp_path,
        {
            "checkpoint_id": "AD-BUG-X",
            "work_type": "repair",
            "status": "ACTIVE",
            "value_gate_status": "NOT_REQUIRED",
        },
    )
    output = run_guard(
        {
            "cwd": str(ROOT),
            "tool_name": "run_in_terminal",
            "tool_input": {"command": "touch docs/ade-os/local-proof.txt"},
        },
        env=env,
    )
    assert output["permissionDecision"] == "allow"


def test_pretool_bootstrap_requires_trusted_python_interpreter(tmp_path: Path) -> None:
    evidence = "/mnt/f/AIOS/anh-duong-checkpoints/AD-X/start.json"
    output = run_guard(
        {
            "cwd": str(ROOT),
            "tool_name": "run_in_terminal",
            "tool_input": {
                "command": f"./python scripts/ade_os.py checkpoint start --evidence {evidence}"
            },
        },
        env=_guard_env(tmp_path),
    )
    assert output["permissionDecision"] == "deny"
    assert "ACTIVE_CHECKPOINT_REQUIRED" in output["permissionDecisionReason"]


def test_pretool_terminal_rejects_expanded_relative_and_compound_escapes(
    tmp_path: Path,
) -> None:
    env = _guard_env(
        tmp_path,
        {
            "checkpoint_id": "AD-BUG-X",
            "work_type": "repair",
            "status": "ACTIVE",
            "value_gate_status": "NOT_REQUIRED",
        },
    )
    commands = (
        "touch ../../anh-duong-core/scripts/ade_os.py",
        "touch ~/AIOS/anh-duong-core/NO",
        "cd ..; touch ad-roadmap-value-gate-1/NO",
        'printf x > "$HOME/.local/state/ade-""os/x/active-checkpoint.json"',
        "/home/thadc/AIOS/anh-duong-core/scripts/ade_os.py doctor",
    )
    for command in commands:
        output = run_guard(
            {
                "cwd": str(ROOT),
                "tool_name": "run_in_terminal",
                "tool_input": {"command": command},
            },
            env=env,
        )
        assert output["permissionDecision"] == "deny", command
        assert "WORKSPACE_SCOPE_FAILURE" in output["permissionDecisionReason"], command


def test_pretool_apply_patch_is_scoped_to_current_allowed_paths(tmp_path: Path) -> None:
    env = _guard_env(
        tmp_path,
        {
            "checkpoint_id": "AD-BUG-X",
            "work_type": "repair",
            "status": "ACTIVE",
            "value_gate_status": "NOT_REQUIRED",
        },
    )
    bad_patches = (
        (
            "*** Begin Patch\n"
            "*** Update File: ../ad-roadmap-value-gate-1/scripts/ade_os.py\n"
            "*** End Patch",
            "WORKSPACE_MISMATCH",
        ),
        (
            "*** Begin Patch\n*** Update File: app/main.py\n*** End Patch",
            "SCOPE_VIOLATION",
        ),
    )
    for patch, expected_code in bad_patches:
        output = run_guard(
            {
                "cwd": str(ROOT),
                "tool_name": "apply_patch",
                "tool_input": {"patch": patch},
            },
            env=env,
        )
        assert output["permissionDecision"] == "deny", patch
        assert expected_code in output["permissionDecisionReason"], patch


def test_pretool_apply_patch_allows_current_approved_path(tmp_path: Path) -> None:
    env = _guard_env(
        tmp_path,
        {
            "checkpoint_id": "AD-BUG-X",
            "work_type": "repair",
            "status": "ACTIVE",
            "value_gate_status": "NOT_REQUIRED",
        },
    )
    output = run_guard(
        {
            "cwd": str(ROOT),
            "tool_name": "apply_patch",
            "tool_input": {
                "patch": (
                    "*** Begin Patch\n"
                    "*** Update File: scripts/ade_os.py\n"
                    "*** End Patch"
                )
            },
        },
        env=env,
    )
    assert output["permissionDecision"] == "allow"



def test_pretool_terminal_rejects_git_c_outside_workspace(tmp_path: Path) -> None:
    env = _guard_env(
        tmp_path,
        {
            "checkpoint_id": "AD-BUG-X",
            "work_type": "repair",
            "status": "ACTIVE",
            "value_gate_status": "NOT_REQUIRED",
        },
    )
    output = run_guard(
        {
            "cwd": str(ROOT),
            "tool_name": "run_in_terminal",
            "tool_input": {"command": "git -C../../anh-duong-core status --short"},
        },
        env=env,
    )
    assert output["permissionDecision"] == "deny"
    assert "WORKSPACE_SCOPE_FAILURE" in output["permissionDecisionReason"]


def test_pretool_terminal_rejects_pathless_container_exec(tmp_path: Path) -> None:
    env = _guard_env(
        tmp_path,
        {
            "checkpoint_id": "AD-BUG-X",
            "work_type": "repair",
            "status": "ACTIVE",
            "value_gate_status": "NOT_REQUIRED",
        },
    )
    output = run_guard(
        {
            "cwd": str(ROOT),
            "tool_name": "run_in_terminal",
            "tool_input": {"command": "docker exec openclaw-openclaw-gateway-1 touch PWNED"},
        },
        env=env,
    )
    assert output["permissionDecision"] == "deny"
    assert "WORKSPACE_SCOPE_FAILURE" in output["permissionDecisionReason"]


def test_pretool_apply_patch_move_validates_destination(tmp_path: Path) -> None:
    env = _guard_env(
        tmp_path,
        {
            "checkpoint_id": "AD-BUG-X",
            "work_type": "repair",
            "status": "ACTIVE",
            "value_gate_status": "NOT_REQUIRED",
        },
    )
    patch = (
        "*** Begin Patch\n"
        "*** Update File: scripts/ade_os.py\n"
        "*** Move to: app/main.py\n"
        "*** End Patch"
    )
    output = run_guard(
        {
            "cwd": str(ROOT),
            "tool_name": "apply_patch",
            "tool_input": {"patch": patch},
        },
        env=env,
    )
    assert output["permissionDecision"] == "deny"
    assert "SCOPE_VIOLATION" in output["permissionDecisionReason"]



def test_pretool_terminal_allows_git_c_current_workspace(tmp_path: Path) -> None:
    env = _guard_env(
        tmp_path,
        {
            "checkpoint_id": "AD-BUG-X",
            "work_type": "repair",
            "status": "ACTIVE",
            "value_gate_status": "NOT_REQUIRED",
        },
    )
    output = run_guard(
        {
            "cwd": str(ROOT),
            "tool_name": "run_in_terminal",
            "tool_input": {"command": "git -C . status --short"},
        },
        env=env,
    )
    assert output["permissionDecision"] == "allow"


def test_pretool_apply_patch_move_inside_allowed_scope_is_allowed(tmp_path: Path) -> None:
    env = _guard_env(
        tmp_path,
        {
            "checkpoint_id": "AD-BUG-X",
            "work_type": "repair",
            "status": "ACTIVE",
            "value_gate_status": "NOT_REQUIRED",
        },
    )
    patch = (
        "*** Begin Patch\n"
        "*** Update File: docs/ade-os/a.md\n"
        "*** Move to: docs/ade-os/b.md\n"
        "*** End Patch"
    )
    output = run_guard(
        {
            "cwd": str(ROOT),
            "tool_name": "apply_patch",
            "tool_input": {"patch": patch},
        },
        env=env,
    )
    assert output["permissionDecision"] == "allow"



def test_pretool_rejects_workspace_python_script_execution(tmp_path: Path) -> None:
    env = _guard_env(
        tmp_path,
        {
            "checkpoint_id": "AD-BUG-X",
            "work_type": "repair",
            "status": "ACTIVE",
            "value_gate_status": "NOT_REQUIRED",
        },
    )
    output = run_guard(
        {
            "cwd": str(ROOT),
            "tool_name": "run_in_terminal",
            "tool_input": {"command": "python3 scripts/ade_os/escape.py"},
        },
        env=env,
    )
    assert output["permissionDecision"] == "deny"
    assert "WORKSPACE_SCOPE_FAILURE" in output["permissionDecisionReason"]


def test_pretool_rejects_direct_workspace_executable(tmp_path: Path) -> None:
    env = _guard_env(
        tmp_path,
        {
            "checkpoint_id": "AD-BUG-X",
            "work_type": "repair",
            "status": "ACTIVE",
            "value_gate_status": "NOT_REQUIRED",
        },
    )
    output = run_guard(
        {
            "cwd": str(ROOT),
            "tool_name": "run_in_terminal",
            "tool_input": {"command": "./scripts/ade_os.py doctor"},
        },
        env=env,
    )
    assert output["permissionDecision"] == "deny"
    assert "WORKSPACE_SCOPE_FAILURE" in output["permissionDecisionReason"]



def test_pretool_rejects_workspace_python_module_execution(tmp_path: Path) -> None:
    env = _guard_env(
        tmp_path,
        {
            "checkpoint_id": "AD-BUG-X",
            "work_type": "repair",
            "status": "ACTIVE",
            "value_gate_status": "NOT_REQUIRED",
        },
    )
    output = run_guard(
        {
            "cwd": str(ROOT),
            "tool_name": "run_in_terminal",
            "tool_input": {"command": "python3 -m scripts.ade_os.escape"},
        },
        env=env,
    )
    assert output["permissionDecision"] == "deny"
    assert "WORKSPACE_SCOPE_FAILURE" in output["permissionDecisionReason"]


def test_pretool_rejects_workspace_script_after_env_assignment(tmp_path: Path) -> None:
    env = _guard_env(
        tmp_path,
        {
            "checkpoint_id": "AD-BUG-X",
            "work_type": "repair",
            "status": "ACTIVE",
            "value_gate_status": "NOT_REQUIRED",
        },
    )
    output = run_guard(
        {
            "cwd": str(ROOT),
            "tool_name": "run_in_terminal",
            "tool_input": {"command": "FLAG=1 python3 scripts/ade_os/escape.py"},
        },
        env=env,
    )
    assert output["permissionDecision"] == "deny"
    assert "WORKSPACE_SCOPE_FAILURE" in output["permissionDecisionReason"]


def test_pretool_rejects_indirect_execution_wrappers(tmp_path: Path) -> None:
    env = _guard_env(
        tmp_path,
        {
            "checkpoint_id": "AD-BUG-X",
            "work_type": "repair",
            "status": "ACTIVE",
            "value_gate_status": "NOT_REQUIRED",
        },
    )
    commands = (
        "env python3 scripts/ade_os/escape.py",
        "timeout 5 python3 scripts/ade_os/escape.py",
        "xargs python3 scripts/ade_os/escape.py",
        "make all",
    )
    for command in commands:
        output = run_guard(
            {
                "cwd": str(ROOT),
                "tool_name": "run_in_terminal",
                "tool_input": {"command": command},
            },
            env=env,
        )
        assert output["permissionDecision"] == "deny", command
        assert "WORKSPACE_SCOPE_FAILURE" in output["permissionDecisionReason"], command


def test_pretool_rejects_find_exec_indirect_execution(tmp_path: Path) -> None:
    env = _guard_env(
        tmp_path,
        {
            "checkpoint_id": "AD-BUG-X",
            "work_type": "repair",
            "status": "ACTIVE",
            "value_gate_status": "NOT_REQUIRED",
        },
    )
    output = run_guard(
        {
            "cwd": str(ROOT),
            "tool_name": "run_in_terminal",
            "tool_input": {"command": "find . -exec python3 scripts/ade_os/escape.py {} +"},
        },
        env=env,
    )
    assert output["permissionDecision"] == "deny"
    assert "WORKSPACE_SCOPE_FAILURE" in output["permissionDecisionReason"]


def test_pretool_rejects_command_resolution_environment_injection(tmp_path: Path) -> None:
    env = _guard_env(
        tmp_path,
        {
            "checkpoint_id": "AD-BUG-X",
            "work_type": "repair",
            "status": "ACTIVE",
            "value_gate_status": "NOT_REQUIRED",
        },
    )
    commands = (
        "PATH=./scripts git status --short",
        "PYTHONPATH=. python3 -m compileall scripts",
        "PYTHONHOME=. python3 -m pytest -q",
        "LD_PRELOAD=./scripts/pwn.so git status --short",
    )
    for command in commands:
        output = run_guard(
            {
                "cwd": str(ROOT),
                "tool_name": "run_in_terminal",
                "tool_input": {"command": command},
            },
            env=env,
        )
        assert output["permissionDecision"] == "deny", command
        assert "WORKSPACE_SCOPE_FAILURE" in output["permissionDecisionReason"], command


def test_pretool_rejects_git_command_extension_injection(tmp_path: Path) -> None:
    env = _guard_env(
        tmp_path,
        {
            "checkpoint_id": "AD-BUG-X",
            "work_type": "repair",
            "status": "ACTIVE",
            "value_gate_status": "NOT_REQUIRED",
        },
    )
    commands = (
        "git -c alias.pwn=!true pwn",
        "git --exec-path=scripts pwn",
        "git config alias.pwn '!true'",
        "git definitely-not-a-builtin",
    )
    for command in commands:
        output = run_guard(
            {
                "cwd": str(ROOT),
                "tool_name": "run_in_terminal",
                "tool_input": {"command": command},
            },
            env=env,
        )
        assert output["permissionDecision"] == "deny", command
        assert "WORKSPACE_SCOPE_FAILURE" in output["permissionDecisionReason"], command


def test_pretool_allows_safe_environment_and_known_git_command(tmp_path: Path) -> None:
    env = _guard_env(
        tmp_path,
        {
            "checkpoint_id": "AD-BUG-X",
            "work_type": "repair",
            "status": "ACTIVE",
            "value_gate_status": "NOT_REQUIRED",
        },
    )
    commands = (
        (
            "PYTHONDONTWRITEBYTECODE=1 "
            "/home/thadc/AIOS/anh-duong-core/.venv/bin/python -I -m pytest -q"
        ),
        "/usr/bin/git -C . status --short",
        "/usr/bin/git diff --check",
    )
    for command in commands:
        output = run_guard(
            {
                "cwd": str(ROOT),
                "tool_name": "run_in_terminal",
                "tool_input": {"command": command},
            },
            env=env,
        )
        assert output["permissionDecision"] == "allow", command


def test_pretool_rejects_remote_api_mutation_commands(tmp_path: Path) -> None:
    env = _guard_env(
        tmp_path,
        {
            "checkpoint_id": "AD-BUG-X",
            "work_type": "repair",
            "status": "ACTIVE",
            "value_gate_status": "NOT_REQUIRED",
        },
    )
    commands = (
        "curl -X POST http://127.0.0.1:8790/admin/restart",
        "/usr/bin/curl -d x=1 https://example.com/mutate",
        "gh api --method DELETE repos/o/r/issues/1",
        "wget --post-data=x https://example.com/mutate",
        "nc 127.0.0.1 8790",
    )
    for command in commands:
        output = run_guard(
            {
                "cwd": str(ROOT),
                "tool_name": "run_in_terminal",
                "tool_input": {"command": command},
            },
            env=env,
        )
        assert output["permissionDecision"] == "deny", command
        assert "WORKSPACE_SCOPE_FAILURE" in output["permissionDecisionReason"], command


def test_pretool_allows_exact_local_health_get_without_checkpoint(tmp_path: Path) -> None:
    env = {**os.environ, "HOME": str(tmp_path / "home")}
    for command in (
        "curl -fsS http://127.0.0.1:8790/health",
        "curl --fail --silent --show-error --max-time 5 http://127.0.0.1:8790/ready",
    ):
        output = run_guard(
            {
                "cwd": str(ROOT),
                "tool_name": "run_in_terminal",
                "tool_input": {"command": command},
            },
            env=env,
        )
        assert output["permissionDecision"] == "allow", command


def test_pretool_rejects_inline_interpreter_eval_variants(tmp_path: Path) -> None:
    env = _guard_env(
        tmp_path,
        {
            "checkpoint_id": "AD-BUG-X",
            "work_type": "repair",
            "status": "ACTIVE",
            "value_gate_status": "NOT_REQUIRED",
        },
    )
    commands = (
        "python3 -c print(1)",
        "node -e fetch('https://example.com')",
        "perl -e print(1)",
        "ruby -e puts(1)",
        "bash -c echo-ok",
    )
    for command in commands:
        output = run_guard(
            {
                "cwd": str(ROOT),
                "tool_name": "run_in_terminal",
                "tool_input": {"command": command},
            },
            env=env,
        )
        assert output["permissionDecision"] == "deny", command
        assert "WORKSPACE_SCOPE_FAILURE" in output["permissionDecisionReason"], command


def test_pretool_rejects_git_remote_and_shared_ref_mutations(tmp_path: Path) -> None:
    env = _guard_env(
        tmp_path,
        {
            "checkpoint_id": "AD-BUG-X",
            "work_type": "repair",
            "status": "ACTIVE",
            "value_gate_status": "NOT_REQUIRED",
        },
    )
    commands = (
        "git push origin HEAD",
        "git remote set-url origin https://example.com/evil.git",
        "git fetch",
        "git fetch origin",
        "git fetch origin main:refs/heads/main",
        "git update-ref refs/heads/main HEAD",
        "git branch -f main HEAD",
        "git worktree prune",
    )
    for command in commands:
        output = run_guard(
            {
                "cwd": str(ROOT),
                "tool_name": "run_in_terminal",
                "tool_input": {"command": command},
            },
            env=env,
        )
        assert output["permissionDecision"] == "deny", command
        assert "WORKSPACE_SCOPE_FAILURE" in output["permissionDecisionReason"], command


def test_pretool_allows_read_only_git_control_queries(tmp_path: Path) -> None:
    env = _guard_env(
        tmp_path,
        {
            "checkpoint_id": "AD-BUG-X",
            "work_type": "repair",
            "status": "ACTIVE",
            "value_gate_status": "NOT_REQUIRED",
        },
    )
    commands = (
        "/usr/bin/git remote get-url origin",
        "/usr/bin/git worktree list --porcelain",
        "/usr/bin/git branch --show-current",
    )
    for command in commands:
        output = run_guard(
            {
                "cwd": str(ROOT),
                "tool_name": "run_in_terminal",
                "tool_input": {"command": command},
            },
            env=env,
        )
        assert output["permissionDecision"] == "allow", command


def test_pretool_rejects_git_branch_switch_or_creation(tmp_path: Path) -> None:
    env = _guard_env(
        tmp_path,
        {
            "checkpoint_id": "AD-BUG-X",
            "work_type": "repair",
            "status": "ACTIVE",
            "value_gate_status": "NOT_REQUIRED",
        },
    )
    commands = (
        "git checkout -b other-lane",
        "git checkout other-lane",
        "git switch -c other-lane",
        "git switch other-lane",
    )
    for command in commands:
        output = run_guard(
            {
                "cwd": str(ROOT),
                "tool_name": "run_in_terminal",
                "tool_input": {"command": command},
            },
            env=env,
        )
        assert output["permissionDecision"] == "deny", command
        assert "WORKSPACE_SCOPE_FAILURE" in output["permissionDecisionReason"], command



def test_pretool_rejects_inherited_path_executable_hijack(tmp_path: Path) -> None:
    env = _guard_env(
        tmp_path,
        {
            "checkpoint_id": "AD-BUG-X",
            "work_type": "repair",
            "status": "ACTIVE",
            "value_gate_status": "NOT_REQUIRED",
        },
    )
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    for name in ("git", "touch"):
        fake = fake_bin / name
        fake.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        fake.chmod(0o755)
    env["PATH"] = f"{fake_bin}:{os.environ.get('PATH', '')}"
    for command in ("git status --short", "touch docs/ade-os/local-proof.txt"):
        output = run_guard(
            {
                "cwd": str(ROOT),
                "tool_name": "run_in_terminal",
                "tool_input": {"command": command},
            },
            env=env,
        )
        assert output["permissionDecision"] == "deny", command


def test_pretool_requires_isolated_trusted_python_for_allowed_modules(tmp_path: Path) -> None:
    env = _guard_env(
        tmp_path,
        {
            "checkpoint_id": "AD-BUG-X",
            "work_type": "repair",
            "status": "ACTIVE",
            "value_gate_status": "NOT_REQUIRED",
        },
    )
    unsafe = run_guard(
        {
            "cwd": str(ROOT),
            "tool_name": "run_in_terminal",
            "tool_input": {
                "command": "/home/thadc/AIOS/anh-duong-core/.venv/bin/python -m pytest -q"
            },
        },
        env=env,
    )
    assert unsafe["permissionDecision"] == "deny"
    safe = run_guard(
        {
            "cwd": str(ROOT),
            "tool_name": "run_in_terminal",
            "tool_input": {
                "command": "/home/thadc/AIOS/anh-duong-core/.venv/bin/python -I -m pytest -q"
            },
        },
        env=env,
    )
    assert safe["permissionDecision"] == "allow"
