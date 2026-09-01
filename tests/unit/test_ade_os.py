"""Focused ADE-OS v1 behavior tests."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
from ade_os import core
import ade_os as package
import importlib.util
SPEC = importlib.util.spec_from_file_location("ade_os_cli", SCRIPTS / "ade_os.py")
assert SPEC and SPEC.loader
CLI = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CLI)


def test_router_precedence_and_escalation() -> None:
    assert core.route_request("Please review and close this checkpoint")["classification"] == "closure"
    assert core.route_request("exit code 127")["classification"] == "terminal-exit"
    assert core.route_request("provider returned 429")["classification"] == "provider-auth"
    assert core.route_request("Bot Telegram lại lỗi")["recommended_agent"] == "ad-diagnose"
    assert core.route_request("fix", failed_repairs=1)["classification"] == "deep-debug"
    assert core.route_request("fix", dirty_unknown=True)["conflict"] is True


def _closure_review(
    *,
    candidate_sha: str = "a" * 40,
    reviewed_sha: str | None = None,
    semantic_review_rounds: int = 1,
    findings_batched: bool = True,
    behavior_changed_after_review: bool = False,
    tool_failures: int = 0,
) -> dict[str, object]:
    return {
        "protocol_version": 1,
        "candidate_sha": candidate_sha,
        "reviewed_sha": reviewed_sha or candidate_sha,
        "candidate_frozen": True,
        "adversarial_matrix_passed": True,
        "focused_regression_passed": True,
        "full_regression_passed": True,
        "reviewer_independent": True,
        "semantic_review_rounds": semantic_review_rounds,
        "findings_batched": findings_batched,
        "behavior_changed_after_review": behavior_changed_after_review,
        "tool_failures": tool_failures,
    }


def _close_gate_evidence() -> dict[str, object]:
    return {
        "conflict_gate": True,
        "scoped_diff": True,
        "tests": True,
        "backup": True,
        "rollback": True,
        "runtime_e2e": True,
        "review": "PASS",
        "closure_review": _closure_review(),
    }


def test_close_gate_requires_e2e_review_and_closure_protocol() -> None:
    evidence = {
        "conflict_gate": True,
        "scoped_diff": True,
        "tests": True,
        "backup": True,
        "rollback": True,
    }
    assert "runtime_e2e" in core.checkpoint_gate(
        {**evidence, "review": "PASS", "closure_review": _closure_review()}, "close"
    )["missing"]
    legacy = core.checkpoint_gate(
        {**evidence, "runtime_e2e": True, "review": "PASS"}, "close"
    )
    assert legacy["status"] == "BLOCKED"
    assert legacy["code"] == "CLOSURE_REVIEW_PROTOCOL_REQUIRED"
    assert core.checkpoint_gate(_close_gate_evidence(), "close")["status"] == "PASS"


def test_closure_review_rejects_stale_candidate_sha() -> None:
    evidence = _close_gate_evidence()
    evidence["closure_review"] = _closure_review(reviewed_sha="b" * 40)
    result = core.checkpoint_gate(evidence, "close")
    assert result["status"] == "BLOCKED"
    assert result["code"] == "REVIEW_CANDIDATE_STALE"


def test_closure_review_budget_allows_one_rereview_only() -> None:
    evidence = _close_gate_evidence()
    evidence["closure_review"] = _closure_review(semantic_review_rounds=3)
    result = core.checkpoint_gate(evidence, "close")
    assert result["status"] == "BLOCKED"
    assert result["code"] == "REVIEW_BUDGET_EXCEEDED"


def test_closure_review_requires_findings_batched_before_rereview() -> None:
    evidence = _close_gate_evidence()
    evidence["closure_review"] = _closure_review(
        semantic_review_rounds=2, findings_batched=False
    )
    result = core.checkpoint_gate(evidence, "close")
    assert result["status"] == "BLOCKED"
    assert result["code"] == "REVIEW_FINDINGS_NOT_BATCHED"


def test_closure_review_tool_failures_do_not_consume_semantic_review_budget() -> None:
    evidence = _close_gate_evidence()
    evidence["closure_review"] = _closure_review(tool_failures=7)
    assert core.checkpoint_gate(evidence, "close")["status"] == "PASS"


def test_closure_review_allows_one_batched_rereview() -> None:
    evidence = _close_gate_evidence()
    evidence["closure_review"] = _closure_review(semantic_review_rounds=2)
    assert core.checkpoint_gate(evidence, "close")["status"] == "PASS"


def test_checkpoint_review_action_requires_closure_protocol() -> None:
    evidence = _close_gate_evidence()
    evidence.pop("closure_review")
    result = core.checkpoint_gate(evidence, "review")
    assert result["status"] == "BLOCKED"
    assert result["code"] == "CLOSURE_REVIEW_PROTOCOL_REQUIRED"


def test_closure_review_fails_if_behavior_changes_after_review() -> None:
    evidence = _close_gate_evidence()
    evidence["closure_review"] = _closure_review(behavior_changed_after_review=True)
    result = core.checkpoint_gate(evidence, "close")
    assert result["status"] == "BLOCKED"
    assert result["code"] == "REVIEW_CANDIDATE_STALE"


def test_memory_redaction_bounded_and_isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "home"))
    for number in range(103): core.append_memory(tmp_path / "one", "last-errors", {"token": "SUPERSECRET", "n": number})
    record = core.read_memory(tmp_path / "one", "last-errors")
    assert len(record["items"]) == 100
    assert "SUPERSECRET" not in json.dumps(record)
    assert core.memory_file(tmp_path / "one", "last-errors") != core.memory_file(tmp_path / "two", "last-errors")


def test_corrupt_memory_is_quarantined(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "home"))
    path = core.memory_file(tmp_path, "last-errors"); path.parent.mkdir(parents=True); path.write_text("not json")
    assert core.read_memory(tmp_path, "last-errors")["items"] == []
    assert list(path.parent.glob("*.corrupt-*"))


def test_project_index_check_and_bug_ranking(tmp_path: Path) -> None:
    (tmp_path / ".ade-os").mkdir(); (tmp_path / "docs").mkdir(); (tmp_path / "STATE.md").write_text("state")
    core.write_index(tmp_path); assert core.write_index(tmp_path, check=True)
    cache = tmp_path / "tests" / "__pycache__"; cache.mkdir(parents=True); (cache / "test.cpython-312.pyc").write_bytes(b"cache")
    assert core.write_index(tmp_path, check=True)
    bugs = tmp_path / "bugs"; bugs.mkdir(); (bugs / "worker.md").write_text("# Worker timeout\ntimeout lease timeout")
    assert core.search_bugs(bugs, "timeout")[0]["id"] == "worker"


def test_cli_close_gate_blocks(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    evidence = tmp_path / "evidence.json"; evidence.write_text(json.dumps({"review": "PASS"}))
    assert CLI.main(["--root", str(ROOT), "checkpoint", "close", "--evidence", str(evidence)]) == 4
    assert json.loads(capsys.readouterr().out)["status"] == "BLOCKED"


def test_cli_review_gate_blocks_with_nonzero_exit(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    evidence = tmp_path / "review.json"
    evidence.write_text(json.dumps(_close_gate_evidence()))
    payload = json.loads(evidence.read_text())
    payload.pop("closure_review")
    evidence.write_text(json.dumps(payload))
    assert CLI.main(["--root", str(ROOT), "checkpoint", "review", "--evidence", str(evidence)]) == 4
    assert json.loads(capsys.readouterr().out)["status"] == "BLOCKED"

def test_ade_route_invocation_without_python_alias(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """ADE route must not exit 127 when shell lacks a `python` alias (only python3/venv)."""
    monkeypatch.chdir(ROOT)
    import subprocess, sys
    result = subprocess.run([sys.executable, "scripts/ade_os.py", "route", "test request"], capture_output=True, text=True)
    assert result.returncode == 0, f"route exit {result.returncode}, stderr: {result.stderr}"
    data = json.loads(result.stdout)
    assert "classification" in data

def test_bare_python_launcher_rejected_by_validator(tmp_path: Path) -> None:
    """validate_customizations must reject bare `python` invocations (RC=127 without venv)."""
    import sys; sys.path.insert(0, str(ROOT / "scripts/agent"))
    from validate_customizations import validate_interpreter_paths
    bad = tmp_path / "bad.prompt.md"
    bad.write_text('---\ndescription: "test"\n---\nRun `python scripts/test.py`.\n')
    errors = validate_interpreter_paths(bad, bad.read_text())
    assert len(errors) == 1
    assert "bare 'python'" in errors[0] and "127" in errors[0]
