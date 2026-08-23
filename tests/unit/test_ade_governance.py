"""Machine-enforced ADE-OS governance tests for AD-L5-01."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from ade_os import core  # noqa: E402


def write_manifest(path: Path, **overrides: object) -> Path:
    payload = {
        "checkpoint_id": "AD-L5-01",
        "code_change": True,
        "production_write": False,
        "service_restart": False,
        "database_write": False,
        "config_write": False,
        "push": False,
        "main_merge": False,
        "max_semantic_repair_rounds": 2,
        "artifact_inside_repo": False,
    }
    payload.update(overrides)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_production_core_path_denied_as_writable_workspace() -> None:
    result = core.validate_workspace(Path("/home/thadc/AIOS/anh-duong-core"), writable=True)
    assert result["status"] == "DENY"
    assert result["reason"] == "GOVERNANCE_FAILURE"


def test_container_core_path_denied_as_writable_workspace() -> None:
    result = core.validate_workspace(Path("/workspaces/anh-duong-core"), writable=True)
    assert result["status"] == "DENY"
    assert result["reason"] == "GOVERNANCE_FAILURE"


def test_valid_registered_worktree_accepted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    worktree_root = tmp_path / "worktrees"
    worktree = worktree_root / "candidate"
    worktree.mkdir(parents=True)
    (worktree / ".git").write_text(
        f"gitdir: {core.PRODUCTION_CORE_ROOT}/.git/worktrees/candidate\n", encoding="utf-8"
    )
    monkeypatch.setattr(core, "CORE_WORKTREE_ROOT", worktree_root)

    result = core.validate_workspace(worktree, writable=True)

    assert result["status"] == "ALLOW"
    assert result["workspace_kind"] == "isolated_worktree"


def test_allowed_paths_escape_denied() -> None:
    result = core.validate_changed_paths(["app/main.py"], allowed_paths=["scripts/ade_os.py"])
    assert result["status"] == "DENY"
    assert result["reason"] == "SCOPE_FAILURE"
    assert result["code"] == "SCOPE_VIOLATION"


def test_unknown_changed_path_fails_closed() -> None:
    result = core.validate_changed_paths(["unknown/new.file"], allowed_paths=["scripts/ade_os.py"])
    assert result["status"] == "DENY"
    assert result["reason"] == "SCOPE_FAILURE"
    assert result["code"] == "SCOPE_VIOLATION"


def test_invalid_or_missing_task_manifest_denied(tmp_path: Path) -> None:
    missing = core.validate_task_manifest(tmp_path / "missing.json", checkpoint_id="AD-L5-01")
    assert missing["status"] == "DENY"
    assert missing["reason"] == "GOVERNANCE_FAILURE"

    invalid_path = write_manifest(tmp_path / "bad.json", checkpoint_id="AD-L5-02")
    invalid = core.validate_task_manifest(invalid_path, checkpoint_id="AD-L5-01")
    assert invalid["status"] == "DENY"
    assert invalid["reason"] == "GOVERNANCE_FAILURE"


def test_production_write_true_denied(tmp_path: Path) -> None:
    manifest = write_manifest(tmp_path / "manifest.json", production_write=True)
    result = core.validate_task_manifest(manifest, checkpoint_id="AD-L5-01")
    assert result["status"] == "DENY"
    assert result["reason"] == "GOVERNANCE_FAILURE"


def test_reviewer_write_attempt_denied() -> None:
    result = core.validate_role_capability("reviewer", "write")
    assert result["status"] == "DENY"
    assert result["reason"] == "GOVERNANCE_FAILURE"


def test_semantic_repair_above_two_blocked() -> None:
    result = core.validate_semantic_repair("DELTA_FAILURE", repair_round=3, max_rounds=2)
    assert result["status"] == "DENY"
    assert result["reason"] == "GOVERNANCE_FAILURE"


@pytest.mark.parametrize("failure_class", ["PRE_EXISTING_FAILURE", "ENVIRONMENT_FAILURE"])
def test_non_delta_failure_cannot_trigger_semantic_repair(failure_class: str) -> None:
    result = core.validate_semantic_repair(failure_class, repair_round=1, max_rounds=2)
    assert result["status"] == "DENY"
    assert result["reason"] == "GOVERNANCE_FAILURE"


def test_failure_classes_are_exact() -> None:
    assert core.FAILURE_CLASSES == (
        "DELTA_FAILURE",
        "PRE_EXISTING_FAILURE",
        "ENVIRONMENT_FAILURE",
        "SCOPE_FAILURE",
        "GOVERNANCE_FAILURE",
    )


def test_result_contract_critical_field_round_trip() -> None:
    payload = {
        "checkpoint_id": "AD-L5-01",
        "status": "READY_FOR_REVIEW",
        "classification": "DELTA_FAILURE",
        "artifacts": ["/mnt/f/AIOS/anh-duong-checkpoints/AD-L5-01/validation.log"],
        "production_write": False,
        "service_restart": False,
        "database_write": False,
        "release_ready": False,
        "custom": "preserved",
    }
    result = core.ResultContract.from_mapping(payload).to_mapping()
    assert result == payload


def test_release_without_all_gates_and_approval_not_release_ready() -> None:
    result = core.evaluate_release_gate({"tests": True, "review": "PASS"}, approved=False)
    assert result["release_ready"] is False
    assert result["performed_release"] is False


def test_runtime_truth_has_no_secret_values() -> None:
    truth = core.runtime_truth(
        {
            "ANH_DUONG_INTERNAL_API_TOKEN": "actual-secret",
            "ANH_DUONG_OPENCLAW_AUTH_TOKEN": "",
            "ANH_DUONG_APP_NAME": "Ánh Dương Core",
        }
    )
    assert truth["env"]["ANH_DUONG_INTERNAL_API_TOKEN"] == "PRESENT"
    assert truth["env"]["ANH_DUONG_OPENCLAW_AUTH_TOKEN"] == "MISSING"
    assert "actual-secret" not in json.dumps(truth)


def test_ownership_matrix_has_current_paths() -> None:
    matrix = core.ownership_matrix()
    assert matrix["core"]["path"] == "/home/thadc/AIOS/anh-duong-core"
    assert matrix["openclaw"]["path"] == "/home/thadc/AIOS/openclaw"
    assert "/mnt/f/AIOS/openclaw" not in json.dumps(matrix)


def test_project_metadata_has_current_ownership_paths() -> None:
    config = core.project_config(ROOT)
    assert config["ownership"]["core"]["path"] == "/home/thadc/AIOS/anh-duong-core"
    assert config["ownership"]["openclaw"]["path"] == "/home/thadc/AIOS/openclaw"
    assert "/mnt/f/AIOS/openclaw" not in json.dumps(config["ownership"])
