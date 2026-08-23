#!/usr/bin/env python3
"""Fail-safe PreToolUse guard for destructive or out-of-scope commands."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ade_os import core

WRITE_TOOLS = {"write", "edit", "multiedit", "notebookedit"}
PATH_KEYS = {"file_path", "path", "notebook_path"}
APPROVED_ALLOWED_PATHS = (
    ".ade-os",
    "scripts/ade_os.py",
    "scripts/ade_os",
    "scripts/agent/pretool_guard.py",
    "scripts/agent/validate_changed.py",
    "scripts/agent/validate_customizations.py",
    ".github/instructions/checkpoint-workflow.instructions.md",
    ".github/instructions/runtime-truth.instructions.md",
    ".github/instructions/safety.instructions.md",
    ".github/instructions/python-quality.instructions.md",
    ".github/prompts/ade-route.prompt.md",
    ".github/prompts/ade-checkpoint-start.prompt.md",
    ".github/prompts/ade-checkpoint-review.prompt.md",
    ".github/prompts/ade-checkpoint-close.prompt.md",
    ".github/hooks",
    "docs/ade-os",
    "tests/unit/test_ade_governance.py",
    "tests/unit/test_ade_workspace_guard.py",
    "tests/unit/test_ade_failure_classifier.py",
    "tests/unit/test_ade_result_contract.py",
    "tests/unit/test_ade_release_gate.py",
    "tests/unit/test_ade_os.py",
    "tests/unit/test_verify_ade_rollback.py",
)


def deny(reason: str) -> int:
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": reason,
                }
            }
        )
    )
    return 0


def text_from(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return " ".join(text_from(item) for item in value.values())
    if isinstance(value, list):
        return " ".join(text_from(item) for item in value)
    return ""


def tool_name(payload: dict[str, Any]) -> str:
    raw = payload.get("tool_name") or payload.get("toolName") or payload.get("name") or ""
    return str(raw).lower()


def tool_input(payload: dict[str, Any]) -> Any:
    return payload.get("tool_input") or payload.get("toolInput") or {}


def path_values(value: Any) -> list[str]:
    if isinstance(value, dict):
        found: list[str] = []
        for key, item in value.items():
            if key in PATH_KEYS and isinstance(item, str):
                found.append(item)
            else:
                found.extend(path_values(item))
        return found
    if isinstance(value, list):
        found_paths: list[str] = []
        for item in value:
            found_paths.extend(path_values(item))
        return found_paths
    return []


def workspace_for_path(path: str) -> str | None:
    candidate = Path(path).resolve(strict=False)
    for root in (core.PRODUCTION_CORE_ROOT, core.CONTAINER_CORE_ROOT):
        if candidate == root or core.is_relative_to(candidate, root):
            return str(root)
    return None


def repo_relative(path: str) -> str:
    candidate = Path(path)
    resolved = candidate.resolve(strict=False)
    root = core.CORE_WORKTREE_ROOT
    if core.is_relative_to(resolved, root):
        parts = resolved.relative_to(root).parts
        return Path(*parts[1:]).as_posix() if len(parts) > 1 else ""
    return candidate.as_posix()


def inferred_write_checks(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if tool_name(payload) not in WRITE_TOOLS:
        return []
    paths = path_values(tool_input(payload))
    if not paths:
        return [
            {
                "status": "DENY",
                "reason": "SCOPE_FAILURE",
                "code": "SCOPE_VIOLATION",
                "details": "Write tool payload did not include an explicit allowed path.",
            }
        ]
    checks: list[dict[str, Any]] = []
    for path in paths:
        if workspace := workspace_for_path(path):
            checks.append(core.validate_workspace(Path(workspace), writable=True))
        else:
            checks.append(
                core.validate_changed_paths(
                    [repo_relative(path)],
                    allowed_paths=list(APPROVED_ALLOWED_PATHS),
                )
            )
    return checks


def governance_checks(payload: dict[str, Any]) -> list[dict[str, Any]]:
    metadata = payload.get("ade_governance")
    checks = inferred_write_checks(payload)
    if not isinstance(metadata, dict):
        return checks
    if "workspace" in metadata:
        checks.append(
            core.validate_workspace(
                Path(str(metadata["workspace"])), writable=bool(metadata.get("writable"))
            )
        )
    if "changed_paths" in metadata or "allowed_paths" in metadata:
        changed = metadata.get("changed_paths")
        allowed = metadata.get("allowed_paths")
        checks.append(
            core.validate_changed_paths(list(changed or []), allowed_paths=list(allowed or []))
        )
    if "task_manifest" in metadata:
        checks.append(
            core.validate_task_manifest(
                Path(str(metadata["task_manifest"])),
                checkpoint_id=str(metadata.get("checkpoint_id", "")),
            )
        )
    if "role" in metadata or "capability" in metadata:
        checks.append(
            core.validate_role_capability(
                str(metadata.get("role", "")), str(metadata.get("capability", ""))
            )
        )
    if "failure_class" in metadata:
        checks.append(
            core.validate_semantic_repair(
                str(metadata["failure_class"]),
                repair_round=int(metadata.get("repair_round", 0)),
                max_rounds=int(metadata.get("max_rounds", 2)),
            )
        )
    return checks


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError):
        return deny("Safety guard could not parse hook input; refusing tool execution.")

    for check in governance_checks(payload):
        if check["status"] != "ALLOW":
            reason = check.get("code") or check["reason"]
            return deny(f"{reason}: {json.dumps(check, sort_keys=True)}")

    command = text_from(payload.get("tool_input") or payload.get("toolInput") or payload)
    compact = " ".join(command.lower().split())
    rules = (
        (
            r"\brm\s+-[a-z]*r[a-z]*f[a-z]*\s+(?:/|~|/mnt/[cf](?:/|\s|$))",
            "Refusing recursive deletion of root, home, or mounted drive.",
        ),
        (
            r"\bgit\s+reset\s+--hard\b",
            "Refusing git reset --hard; it can destroy uncommitted work.",
        ),
        (
            r"\bgit\s+clean\s+-[^\n]*f",
            "Refusing git clean with force; it can destroy untracked work.",
        ),
        (
            r"\bgit\s+checkout\s+--\s+\.\b",
            "Refusing broad git checkout; it can destroy uncommitted work.",
        ),
        (r"\bgit\s+stash\b", "Refusing git stash; active changes require explicit preservation."),
        (r"\bgit\s+push\s+.*--force", "Refusing force push."),
        (r"\bdocker\s+(system\s+prune|volume\s+rm)\b", "Refusing destructive Docker cleanup."),
        (
            r"\b(systemctl|service)\s+(stop|disable)\b",
            "Refusing service stop/disable outside explicit scope.",
        ),
        (r"\b(drop|truncate)\s+(database|table)\b", "Refusing destructive SQL."),
        (
            r"\b(cat|printenv|env)\b.*\b(token|api[_-]?key|password|secret|authorization)\b",
            "Refusing command likely to print credentials.",
        ),
        (r"\bchmod\s+-R\b", "Refusing mass permission change."),
    )
    for pattern, reason in rules:
        if re.search(pattern, compact):
            return deny(reason)
    print(
        json.dumps(
            {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow"}}
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
