"""CLI coverage for the checkpoint value/native-capability gate."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_value_gate_cli_emits_machine_readable_allow(tmp_path: Path) -> None:
    manifest = tmp_path / "value-gate.json"
    manifest.write_text(
        json.dumps(
            {
                "user_value": "Finish work with less human babysitting.",
                "measurement": "Verified completion rate.",
                "revenue_link": "DIRECT_REVENUE",
                "content_proof": "Before/after demo.",
                "native_capability": {
                    "decision": "WRAP_NATIVE",
                    "coverage_pct": 90,
                    "owned_contract": False,
                    "rationale": "Use native executor; keep governance in Ánh Dương.",
                },
            }
        ),
        encoding="utf-8",
    )
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/ade_os.py"),
            "value-gate",
            "--manifest",
            str(manifest),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "ALLOW"
    assert payload["native_decision"] == "WRAP_NATIVE"


def test_value_gate_cli_returns_nonzero_for_denied_manifest(tmp_path: Path) -> None:
    manifest = tmp_path / "denied.json"
    manifest.write_text("[]", encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/ade_os.py"),
            "value-gate",
            "--manifest",
            str(manifest),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 4
    payload = json.loads(result.stdout)
    assert payload["status"] == "DENY"
    assert payload["code"] == "INVALID_MANIFEST"


def _feature_start_evidence() -> dict[str, object]:
    return {
        "checkpoint_id": "AD-FEATURE-X",
        "work_type": "feature",
        "value_gate": {
            "user_value": "Reduce human intervention.",
            "measurement": "Verified completion rate.",
            "revenue_link": "INDIRECT_REVENUE",
            "content_proof": "Before/after demo.",
            "native_capability": {
                "decision": "WRAP_NATIVE",
                "coverage_pct": 90,
                "owned_contract": False,
                "rationale": "Use native execution and keep governance local.",
            },
        },
    }


def _project_root(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    config_dir = root / ".ade-os"
    config_dir.mkdir(parents=True)
    artifact_root = tmp_path / "artifacts"
    (config_dir / "project.yaml").write_text(
        json.dumps({"version": 1, "artifact_path": str(artifact_root)}),
        encoding="utf-8",
    )
    subprocess.run(["git", "-C", str(root), "init", "-b", "main"], check=True)
    subprocess.run(
        ["git", "-C", str(root), "config", "user.email", "test@example.invalid"], check=True
    )
    subprocess.run(["git", "-C", str(root), "config", "user.name", "ADE Test"], check=True)
    subprocess.run(["git", "-C", str(root), "add", ".ade-os/project.yaml"], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-m", "base"], check=True)
    return root


def _write_start_artifacts(root: Path, payload: dict[str, object]) -> Path:
    config = json.loads((root / ".ade-os/project.yaml").read_text(encoding="utf-8"))
    directory = Path(config["artifact_path"]) / str(payload["checkpoint_id"])
    directory.mkdir(parents=True, exist_ok=True)
    value_gate = payload.get("value_gate")
    if isinstance(value_gate, dict):
        (directory / "value-gate.json").write_text(json.dumps(value_gate), encoding="utf-8")
    start = directory / "start.json"
    start.write_text(json.dumps(payload), encoding="utf-8")
    return start


def test_checkpoint_start_cli_blocks_missing_value_gate(tmp_path: Path) -> None:
    evidence = tmp_path / "start.json"
    evidence.write_text(
        json.dumps({"checkpoint_id": "AD-FEATURE-X", "work_type": "feature"}),
        encoding="utf-8",
    )
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/ade_os.py"),
            "checkpoint",
            "start",
            "--evidence",
            str(evidence),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 4
    assert json.loads(result.stdout)["status"] == "BLOCKED"


def test_checkpoint_start_cli_persists_active_value_gate_state(tmp_path: Path) -> None:
    root = _project_root(tmp_path)
    evidence = _write_start_artifacts(root, _feature_start_evidence())
    home = tmp_path / "home"
    result = _cli(["checkpoint", "start", "--evidence", str(evidence)], home, root=root)
    assert result.returncode == 0
    payload = json.loads(_state_path(home, root=root).read_text(encoding="utf-8"))
    active = payload["items"][-1]
    assert active["status"] == "ACTIVE"
    assert active["checkpoint_id"] == "AD-FEATURE-X"
    assert active["value_gate_status"] == "ALLOW"


def _cli(
    args: list[str],
    home: Path,
    *,
    root: Path = ROOT,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts/ade_os.py"), "--root", str(root), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
        env={**os.environ, "HOME": str(home)},
    )


def _state_path(home: Path, *, root: Path = ROOT) -> Path:
    digest = hashlib.sha256(str(root.resolve()).encode()).hexdigest()[:16]
    return home / ".local/state/ade-os" / digest / "active-checkpoint.json"


def test_memory_set_checkpoint_cannot_forge_active_state(tmp_path: Path) -> None:
    home = tmp_path / "home"
    forged = {
        "checkpoint_id": "FORGED",
        "work_type": "feature",
        "status": "ACTIVE",
        "value_gate_status": "ALLOW",
    }
    result = _cli(["memory", "set-checkpoint", "--data", json.dumps(forged)], home)
    assert result.returncode == 4
    assert not _state_path(home).exists()


def test_checkpoint_start_blocks_second_active_checkpoint(tmp_path: Path) -> None:
    home = tmp_path / "home"
    root = _project_root(tmp_path)
    first = _write_start_artifacts(root, _feature_start_evidence())
    assert _cli(["checkpoint", "start", "--evidence", str(first)], home, root=root).returncode == 0
    second_payload = {"checkpoint_id": "AD-SECOND", "work_type": "repair"}
    second = _write_start_artifacts(root, second_payload)
    result = _cli(["checkpoint", "start", "--evidence", str(second)], home, root=root)
    assert result.returncode == 4
    state = json.loads(_state_path(home, root=root).read_text(encoding="utf-8"))
    assert state["items"][-1]["checkpoint_id"] == "AD-FEATURE-X"
    assert state["items"][-1]["status"] == "ACTIVE"


def _close_evidence(checkpoint_id: str, root: Path) -> dict[str, object]:
    sha = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()
    diff = subprocess.run(
        ["git", "-C", str(root), "diff", "--binary", "--full-index", f"{sha}..{sha}"],
        capture_output=True,
        check=True,
    ).stdout
    diff_hash = hashlib.sha256(diff).hexdigest()
    return {
        "checkpoint_id": checkpoint_id,
        "conflict_gate": True,
        "scoped_diff": True,
        "tests": True,
        "backup": True,
        "rollback": True,
        "review": "PASS",
        "closure_review": {
            "protocol_version": 1,
            "base_sha": sha,
            "candidate_sha": sha,
            "reviewed_sha": sha,
            "merge_sha": sha,
            "locked_diff_sha256": diff_hash,
            "reviewed_diff_sha256": diff_hash,
            "merge_diff_sha256": diff_hash,
            "candidate_locked": True,
            "candidate_clean": True,
            "source_generation": 1,
            "adversarial_generation": 1,
            "targeted_generation": 1,
            "static_generation": 1,
            "full_regression_generation": 1,
            "review_generation": 1,
            "reviewer_independent": True,
            "reviewer_status": "COMPLETED",
            "review_verdict": "PASS",
            "p0": 0,
            "p1": 0,
            "p2": 0,
            "final_review_count": 1,
            "rereview_reason": None,
            "finding_batch_id": None,
            "findings_batched": True,
            "last_finding_batch_generation": None,
            "tool_failures": 0,
            "runtime_mode": "SOURCE_ONLY",
            "deployed": False,
            "runtime_e2e": False,
        },
    }


def test_checkpoint_close_must_match_active_checkpoint(tmp_path: Path) -> None:
    home = tmp_path / "home"
    root = _project_root(tmp_path)
    start = _write_start_artifacts(root, _feature_start_evidence())
    assert _cli(["checkpoint", "start", "--evidence", str(start)], home, root=root).returncode == 0
    close = tmp_path / "close.json"
    close.write_text(json.dumps(_close_evidence("AD-OTHER", root)), encoding="utf-8")
    result = _cli(["checkpoint", "close", "--evidence", str(close)], home, root=root)
    assert result.returncode == 4
    state = json.loads(_state_path(home, root=root).read_text(encoding="utf-8"))
    assert state["items"][-1]["checkpoint_id"] == "AD-FEATURE-X"
    assert state["items"][-1]["status"] == "ACTIVE"


def test_checkpoint_start_same_active_checkpoint_is_idempotent(tmp_path: Path) -> None:
    home = tmp_path / "home"
    root = _project_root(tmp_path)
    evidence = _write_start_artifacts(root, _feature_start_evidence())
    args = ["checkpoint", "start", "--evidence", str(evidence)]
    assert _cli(args, home, root=root).returncode == 0
    assert _cli(args, home, root=root).returncode == 0
    state = json.loads(_state_path(home, root=root).read_text(encoding="utf-8"))
    assert len(state["items"]) == 1


def test_checkpoint_close_matching_active_checkpoint_records_close(tmp_path: Path) -> None:
    home = tmp_path / "home"
    root = _project_root(tmp_path)
    start = _write_start_artifacts(root, _feature_start_evidence())
    assert _cli(["checkpoint", "start", "--evidence", str(start)], home, root=root).returncode == 0
    close = tmp_path / "close.json"
    close.write_text(json.dumps(_close_evidence("AD-FEATURE-X", root)), encoding="utf-8")
    assert _cli(["checkpoint", "close", "--evidence", str(close)], home, root=root).returncode == 0
    state = json.loads(_state_path(home, root=root).read_text(encoding="utf-8"))
    assert state["items"][-1]["status"] == "CLOSE"


def test_checkpoint_start_cli_rejects_forged_evidence_outside_artifact_directory(
    tmp_path: Path,
) -> None:
    evidence = tmp_path / "forged-start.json"
    evidence.write_text(json.dumps(_feature_start_evidence()), encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/ade_os.py"),
            "checkpoint",
            "start",
            "--evidence",
            str(evidence),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
        env={**os.environ, "HOME": str(tmp_path / "home")},
    )
    assert result.returncode == 4
    assert json.loads(result.stdout)["code"] == "CHECKPOINT_PROVENANCE_FAILURE"
