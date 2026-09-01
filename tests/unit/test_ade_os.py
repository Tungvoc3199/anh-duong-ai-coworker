"""Focused ADE-OS v1 behavior tests."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
from ade_os import core  # noqa: E402

SPEC = importlib.util.spec_from_file_location("ade_os_cli", SCRIPTS / "ade_os.py")
assert SPEC and SPEC.loader
CLI = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CLI)


def _valid_closure_review() -> dict[str, object]:
    sha = "a" * 40
    diff_hash = "1" * 64
    return {
        "protocol_version": 1,
        "base_sha": "0" * 40,
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
    }


def test_router_precedence_and_escalation() -> None:
    assert (
        core.route_request("Please review and close this checkpoint")["classification"] == "closure"
    )
    assert core.route_request("exit code 127")["classification"] == "terminal-exit"
    assert core.route_request("provider returned 429")["classification"] == "provider-auth"
    assert core.route_request("Bot Telegram lại lỗi")["recommended_agent"] == "ad-diagnose"
    assert core.route_request("fix", failed_repairs=1)["classification"] == "deep-debug"
    assert core.route_request("fix", dirty_unknown=True)["conflict"] is True


def test_close_gate_requires_review_protocol_not_fake_runtime_e2e() -> None:
    evidence = {
        "conflict_gate": True,
        "scoped_diff": True,
        "tests": True,
        "backup": True,
        "rollback": True,
        "review": "PASS",
    }
    blocked = core.checkpoint_gate(evidence, "close")
    assert blocked["code"] == "CLOSURE_REVIEW_PROTOCOL_REQUIRED"
    evidence["closure_review"] = _valid_closure_review()
    root_required = core.checkpoint_gate(evidence, "close")
    assert root_required["status"] == "BLOCKED"
    assert root_required["code"] == "REPOSITORY_VALIDATION_REQUIRED"
    assert (
        core.validate_closure_review_protocol(_valid_closure_review(), action="close")["status"]
        == "PASS"
    )


def test_memory_redaction_bounded_and_isolated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "home"))
    for number in range(103):
        core.append_memory(tmp_path / "one", "last-errors", {"token": "SUPERSECRET", "n": number})
    record = core.read_memory(tmp_path / "one", "last-errors")
    assert len(record["items"]) == 100
    assert "SUPERSECRET" not in json.dumps(record)
    assert core.memory_file(tmp_path / "one", "last-errors") != core.memory_file(
        tmp_path / "two", "last-errors"
    )


def test_corrupt_memory_is_quarantined(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "home"))
    path = core.memory_file(tmp_path, "last-errors")
    path.parent.mkdir(parents=True)
    path.write_text("not json")
    assert core.read_memory(tmp_path, "last-errors")["items"] == []
    assert list(path.parent.glob("*.corrupt-*"))


def test_project_index_check_and_bug_ranking(tmp_path: Path) -> None:
    (tmp_path / ".ade-os").mkdir()
    (tmp_path / "docs").mkdir()
    (tmp_path / "STATE.md").write_text("state")
    core.write_index(tmp_path)
    assert core.write_index(tmp_path, check=True)
    cache = tmp_path / "tests" / "__pycache__"
    cache.mkdir(parents=True)
    (cache / "test.cpython-312.pyc").write_bytes(b"cache")
    assert core.write_index(tmp_path, check=True)
    bugs = tmp_path / "bugs"
    bugs.mkdir()
    (bugs / "worker.md").write_text("# Worker timeout\ntimeout lease timeout")
    assert core.search_bugs(bugs, "timeout")[0]["id"] == "worker"


def test_cli_close_gate_blocks(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    evidence = tmp_path / "evidence.json"
    evidence.write_text(json.dumps({"review": "PASS"}))
    assert CLI.main(["--root", str(ROOT), "checkpoint", "close", "--evidence", str(evidence)]) == 4
    assert json.loads(capsys.readouterr().out)["status"] == "BLOCKED"


def test_ade_route_invocation_without_python_alias(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADE route must not exit 127 when shell lacks a `python` alias (only python3/venv)."""
    monkeypatch.chdir(ROOT)
    result = subprocess.run(
        [sys.executable, "scripts/ade_os.py", "route", "test request"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"route exit {result.returncode}, stderr: {result.stderr}"
    data = json.loads(result.stdout)
    assert "classification" in data


def test_bare_python_launcher_rejected_by_validator(tmp_path: Path) -> None:
    """validate_customizations must reject bare `python` invocations (RC=127 without venv)."""
    sys.path.insert(0, str(ROOT / "scripts/agent"))
    from validate_customizations import validate_interpreter_paths

    bad = tmp_path / "bad.prompt.md"
    bad.write_text('---\ndescription: "test"\n---\nRun `python scripts/test.py`.\n')
    errors = validate_interpreter_paths(bad, bad.read_text())
    assert len(errors) == 1
    assert "bare 'python'" in errors[0] and "127" in errors[0]


@pytest.mark.parametrize("action", ["review", "close"])
def test_review_close_parser_requires_explicit_repository_root(action: str) -> None:
    args = CLI.parser().parse_args(["checkpoint", action])
    assert args.root is None


@pytest.mark.parametrize("action", ["review", "close"])
def test_review_close_cli_without_root_fails_closed(action: str) -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPTS / "ade_os.py"), "checkpoint", action],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 4
    assert json.loads(result.stdout)["code"] == "REPOSITORY_VALIDATION_REQUIRED"
