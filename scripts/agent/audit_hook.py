#!/usr/bin/env python3
"""Best-effort, redacted hook audit log. Never blocks agent execution."""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

SECRET = re.compile(r"(?i)(authorization\s*[:=]\s*(?:bearer\s+)?|api[_-]?key\s*[:=]|token\s*[:=]|password\s*[:=]|secret\s*[:=])([^\s,;\"']+)")
HOME_SECRET = re.compile(r"(?i)(sk-[a-z0-9_-]{8,}|gh[pousr]_[a-z0-9_]{8,})")


def redact(value: Any) -> Any:
    if isinstance(value, str):
        return HOME_SECRET.sub("<redacted>", SECRET.sub(r"\1<redacted>", value))
    if isinstance(value, dict):
        return {str(key): ("<redacted>" if re.search(r"(?i)(token|secret|password|api[_-]?key|authorization)", str(key)) else redact(item)) for key, item in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


def audit_path() -> Path:
    primary = Path("/mnt/f/AIOS/anh-duong-checkpoints/vscode-agent-audit")
    try:
        primary.mkdir(parents=True, exist_ok=True)
        if os.access(primary, os.W_OK):
            return primary / "hooks.jsonl"
    except OSError:
        pass
    fallback = Path.home() / ".local/state/anh-duong-core/vscode-agent-audit"
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback / "hooks.jsonl"


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        record = {"utc": dt.datetime.now(dt.timezone.utc).isoformat(), "event": payload.get("hook_event_name") or payload.get("hookEventName") or "unknown", "payload": redact(payload)}
        with audit_path().open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
