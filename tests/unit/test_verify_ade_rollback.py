"""Focused tests for the isolated ADE-OS rollback verifier."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("verify_ade_rollback", ROOT / "scripts/agent/verify_ade_rollback.py")
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def make_backup(path: Path) -> None:
    for item in MODULE.BASELINE:
        target = path / item
        target.parent.mkdir(parents=True, exist_ok=True)
        if Path(item).suffix:
            target.write_text(item)
        else:
            target.mkdir(exist_ok=True)
    agents = path / "user-copilot-agents"
    agents.mkdir()
    for name in ("ad-diagnose.agent.md", "ad-fix.agent.md", "ad-deep-debug.agent.md", "ad-orchestrator.agent.md", "ad-review.agent.md"):
        (agents / name).write_text(name)


def test_verify_blocks_incomplete_backup(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="missing backup paths"):
        MODULE.verify(tmp_path / "root", tmp_path / "backup", tmp_path)


def test_untracked_ownership_is_explicit() -> None:
    assert MODULE.allowed_untracked("scripts/agent/verify_ade_rollback.py")
    assert MODULE.allowed_untracked("tests/unit/test_ade_os.py")
    assert MODULE.allowed_untracked(".github/hooks/audit.json")
    assert not MODULE.allowed_untracked("scripts/agent/foreign.py")
    assert not MODULE.allowed_untracked(".github/agents/foreign.agent.md")


def test_verify_preserves_guards_in_sandbox(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "root"; backup = tmp_path / "backup"; artifacts = tmp_path / "artifacts"
    root.mkdir(); artifacts.mkdir(); make_backup(backup)
    for item in MODULE.PROTECTED + MODULE.PLUGIN:
        target = root / item; target.parent.mkdir(parents=True, exist_ok=True); target.write_text(item)
    for item in MODULE.BASELINE + MODULE.ADE_ONLY:
        if item.startswith("user-copilot-agents/"): continue
        target = root / item; target.parent.mkdir(parents=True, exist_ok=True)
        if Path(item).suffix: target.write_text("current")
        else: target.mkdir(exist_ok=True)
    home = tmp_path / "home"; agent = home / ".copilot/agents/ad-project.agent.md"; agent.parent.mkdir(parents=True); agent.write_text("project")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    result = MODULE.verify(root, backup, artifacts)
    assert result["status"] == "PASS"
    assert result["protected"] == {item: MODULE.digest(root / item) for item in MODULE.PROTECTED}
