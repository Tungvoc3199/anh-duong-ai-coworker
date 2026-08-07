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


def test_close_gate_requires_e2e_and_review() -> None:
    evidence = {"conflict_gate": True, "scoped_diff": True, "tests": True, "backup": True, "rollback": True}
    assert "runtime_e2e" in core.checkpoint_gate({**evidence, "review": "PASS"}, "close")["missing"]
    assert core.checkpoint_gate({**evidence, "runtime_e2e": True, "review": "PASS"}, "close")["status"] == "PASS"


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
    assert CLI.main(["--root", str(ROOT), "checkpoint", "close", "--evidence", str(evidence)]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "BLOCKED"
