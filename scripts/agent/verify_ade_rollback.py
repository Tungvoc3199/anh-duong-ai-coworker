#!/usr/bin/env python3
"""Dry-run ADE-OS rollback verification; never modifies the real workspace."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path("/home/thadc/AIOS/anh-duong-core")
BACKUP = Path("/mnt/f/AIOS/anh-duong-checkpoints/ADE-OS-backup-20260806T174329Z")
ARTIFACTS = Path("/mnt/f/AIOS/anh-duong-checkpoints")
PROTECTED = (
    "app/async_tasks/worker.py", "app/openclaw/executor.py",
    "tests/integration/test_async_task_worker.py", "tests/unit/test_openclaw_executor.py",
)
PLUGIN = (
    "integrations/openclaw-anh-duong-core/src/hooks.js",
    "integrations/openclaw-anh-duong-core/test/hooks.test.js",
)
BASELINE = ("AGENTS.md", ".github/instructions", ".github/prompts", ".github/hooks", ".vscode/settings.json", "scripts/agent")
ADE_ONLY = (
    ".ade-os", "scripts/ade_os.py", "scripts/ade_os", "docs/ade-os",
    ".github/prompts/ade-bug.prompt.md", ".github/prompts/ade-checkpoint-diagnose.prompt.md",
    ".github/prompts/ade-checkpoint-fix.prompt.md", ".github/prompts/ade-checkpoint-review.prompt.md",
    ".github/prompts/ade-memory.prompt.md", ".github/prompts/ade-route.prompt.md",
    ".github/prompts/ade-status.prompt.md", "user-copilot-agents/ad-project.agent.md",
    "scripts/agent/verify_ade_rollback.py", "tests/unit/test_ade_os.py",
    "tests/unit/test_verify_ade_rollback.py",
)

def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            value.update(chunk)
    return value.hexdigest()

def copy_path(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if source.is_dir(): shutil.copytree(source, target, dirs_exist_ok=True)
    else: shutil.copy2(source, target)

def files(root: Path) -> dict[str, str]:
    return {str(path.relative_to(root)): digest(path) for path in sorted(root.rglob("*")) if path.is_file()}

def untracked(root: Path) -> tuple[str, ...]:
    completed = subprocess.run(["git", "status", "--porcelain=v1", "--untracked-files=all"], cwd=root, check=True, capture_output=True, text=True)
    return tuple(line[3:] for line in completed.stdout.splitlines() if line.startswith("?? "))

def allowed_untracked(path: str) -> bool:
    baseline_files = set(files(BACKUP))
    baseline_paths = set(BASELINE)
    baseline_prefixes = tuple(
        f"{item.rstrip('/')}/".replace("\\/", "/")
        for item in BASELINE
        if not Path(item).suffix
    )
    ade_files = {
        "AGENTS.md", "scripts/ade_os.py", "scripts/agent/verify_ade_rollback.py",
        "tests/unit/test_ade_os.py", "tests/unit/test_verify_ade_rollback.py",
    }
    ade_prefixes = (".ade-os/", "docs/ade-os/", "scripts/ade_os/")
    evidence_prefixes = (
        "integrations/openclaw-anh-duong-core/src/hooks.js.AD-TXT-1.",
        "integrations/openclaw-anh-duong-core/test/hooks.test.js.AD-TXT-1.",
    )
    return (
        path in baseline_files
        or path in baseline_paths
        or path.startswith(baseline_prefixes)
        or path in ADE_ONLY
        or path in ade_files
        or path.startswith(ade_prefixes + evidence_prefixes)
    )

def verify(root: Path = ROOT, backup: Path = BACKUP, artifacts: Path = ARTIFACTS) -> dict[str, object]:
    if root.resolve() == ROOT:
        foreign = [path for path in untracked(root) if not allowed_untracked(path)]
        if foreign: raise RuntimeError(f"unowned untracked paths block rollback: {foreign}")
    missing = [path for path in BASELINE if not (backup / path).exists()]
    if missing: raise RuntimeError(f"missing backup paths: {missing}")
    if not all((backup / "user-copilot-agents" / name).is_file() for name in ("ad-diagnose.agent.md", "ad-fix.agent.md", "ad-deep-debug.agent.md", "ad-orchestrator.agent.md", "ad-review.agent.md")):
        raise RuntimeError("baseline user agents are incomplete")
    protected_before = {path: digest(root / path) for path in PROTECTED}
    plugin_before = {path: digest(root / path) for path in PLUGIN}
    with tempfile.TemporaryDirectory(prefix="ade-rollback-dry-run-", dir=artifacts) as temporary:
        sandbox = Path(temporary) / "workspace"
        sandbox.mkdir()
        for path in BASELINE + ADE_ONLY:
            source = root / path if not path.startswith("user-copilot-agents/") else Path.home() / ".copilot/agents" / "ad-project.agent.md"
            if source.exists(): copy_path(source, sandbox / path)
        for path in PROTECTED + PLUGIN:
            copy_path(root / path, sandbox / path)
        for path in BASELINE:
            target = sandbox / path
            if target.exists():
                if target.is_dir(): shutil.rmtree(target)
                else: target.unlink()
            copy_path(backup / path, target)
        copy_path(backup / "user-copilot-agents", sandbox / "user-copilot-agents")
        for path in ADE_ONLY:
            target = sandbox / path
            if target.exists():
                if target.is_dir(): shutil.rmtree(target)
                else: target.unlink()
        baseline_expected = files(backup)
        baseline_actual = files(sandbox)
        for path, expected in baseline_expected.items():
            if path != "inventory.txt" and baseline_actual.get(path) != expected:
                raise RuntimeError(f"baseline restore mismatch: {path}")
        if {path: digest(sandbox / path) for path in PROTECTED} != protected_before: raise RuntimeError("protected-file guard failed")
        if {path: digest(sandbox / path) for path in PLUGIN} != plugin_before: raise RuntimeError("AD plugin guard failed")
    return {"status": "PASS", "protected": protected_before, "plugin": plugin_before, "baseline_files": len(baseline_expected) - 1}

def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try: result = verify()
    except (OSError, RuntimeError) as error:
        print(json.dumps({"status": "BLOCKED", "error": str(error)})); return 1
    text = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output: args.output.write_text(text, encoding="utf-8")
    print(text, end=""); return 0

if __name__ == "__main__": raise SystemExit(main())
