#!/usr/bin/env python3
"""Bounded PostToolUse validation for changed customization and Python files."""
from __future__ import annotations

import json
import py_compile
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
CUSTOM_SUFFIXES = (".agent.md", ".prompt.md", ".instructions.md")


def strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        result: list[str] = []
        for item in value.values(): result.extend(strings(item))
        return result
    if isinstance(value, list):
        result: list[str] = []
        for item in value: result.extend(strings(item))
        return result
    return []


def candidates(payload: dict[str, Any]) -> set[Path]:
    found: set[Path] = set()
    for raw in strings(payload.get("tool_input") or payload.get("toolInput") or {}):
        try:
            path = Path(raw)
            if not path.is_absolute(): path = ROOT / path
            resolved = path.resolve()
            if resolved.is_file() and ROOT in resolved.parents:
                found.add(resolved)
        except OSError:
            continue
    return found


def check(path: Path) -> str | None:
    try:
        if path.suffix == ".py":
            py_compile.compile(str(path), doraise=True)
        elif path.suffix == ".json":
            json.loads(path.read_text(encoding="utf-8"))
        elif path.suffix == ".sh":
            result = subprocess.run(["bash", "-n", str(path)], capture_output=True, text=True, timeout=10)
            if result.returncode: return result.stderr.strip() or "bash syntax failure"
        elif path.name.endswith(CUSTOM_SUFFIXES):
            result = subprocess.run([sys.executable, str(ROOT / "scripts/agent/validate_customizations.py"), str(path)], capture_output=True, text=True, timeout=15)
            if result.returncode: return result.stderr.strip() or result.stdout.strip()
    except Exception as exc:
        return f"{path}: {exc}"
    return None


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    failures = [error for path in candidates(payload) if (error := check(path))]
    if failures:
        print("Scoped validation warning: " + " | ".join(failures), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
