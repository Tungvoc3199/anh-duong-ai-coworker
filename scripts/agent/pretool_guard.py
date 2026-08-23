#!/usr/bin/env python3
"""Fail-safe PreToolUse guard for destructive or out-of-scope commands."""
from __future__ import annotations

import json
import re
import sys
from typing import Any


def deny(reason: str) -> int:
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": reason,
    }}))
    return 0


def text_from(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return " ".join(text_from(item) for item in value.values())
    if isinstance(value, list):
        return " ".join(text_from(item) for item in value)
    return ""


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError):
        return deny("Safety guard could not parse hook input; refusing tool execution.")

    command = text_from(payload.get("tool_input") or payload.get("toolInput") or payload)
    compact = " ".join(command.lower().split())
    rules = (
        (r"\brm\s+-[a-z]*r[a-z]*f[a-z]*\s+(?:/|~|/mnt/[cf](?:/|\s|$))", "Refusing recursive deletion of root, home, or mounted drive."),
        (r"\bgit\s+reset\s+--hard\b", "Refusing git reset --hard; it can destroy uncommitted work."),
        (r"\bgit\s+clean\s+-[^\n]*f", "Refusing git clean with force; it can destroy untracked work."),
        (r"\bgit\s+checkout\s+--\s+\.\b", "Refusing broad git checkout; it can destroy uncommitted work."),
        (r"\bgit\s+stash\b", "Refusing git stash; active changes require explicit preservation."),
        (r"\bgit\s+push\s+.*--force", "Refusing force push."),
        (r"\bdocker\s+(system\s+prune|volume\s+rm)\b", "Refusing destructive Docker cleanup."),
        (r"\b(systemctl|service)\s+(stop|disable)\b", "Refusing service stop/disable outside explicit scope."),
        (r"\b(drop|truncate)\s+(database|table)\b", "Refusing destructive SQL."),
        (r"\b(cat|printenv|env)\b.*\b(token|api[_-]?key|password|secret|authorization)\b", "Refusing command likely to print credentials."),
        (r"\bchmod\s+-R\b", "Refusing mass permission change."),
    )
    for pattern, reason in rules:
        if re.search(pattern, compact):
            return deny(reason)
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse", "permissionDecision": "allow"
    }}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
