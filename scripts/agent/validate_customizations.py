#!/usr/bin/env python3
"""Validate JSON and minimal YAML frontmatter without third-party packages."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

VALID_SUFFIXES = (".agent.md", ".prompt.md", ".instructions.md")
REQUIRED = {".agent.md": {"description"}, ".instructions.md": {"description", "applyTo"}}
KEY = re.compile(r"^([A-Za-z][A-Za-z0-9_-]*):(?:\s|$)")

# Hook event names accepted by the current VS Code hook executor.
VALID_HOOK_EVENTS = {
    "PreToolUse", "PostToolUse", "PostToolUseFailure", "Notification",
    "UserPromptSubmit", "SessionStart", "SessionEnd", "Stop", "StopFailure",
    "SubagentStart", "SubagentStop", "PreCompact", "PostCompact",
    "PermissionRequest", "PermissionDenied", "Setup",
}
# The executor does NOT expand ${...} in "cwd" or "command"; an unexpanded
# variable becomes a literal path segment and spawn fails with the misleading
# error "spawn /bin/sh ENOENT". Absolute paths are therefore mandatory.
SHELL_LAUNCHERS = ("/bin/sh", "sh -lc", "bash -lc", "sh -c ", "bash -c ")

# The shell has no `python` alias on this host (only `python3` and the project
# venv), so a bare `python ...` invocation in any ADE-owned file exits 127 with
# "Command 'python' not found". Require an absolute interpreter path instead.
VENV_PYTHON = "/home/thadc/AIOS/anh-duong-core/.venv/bin/python"
BARE_PYTHON = re.compile(r"(?<![\w./-])python3?\s+(?=-m\b|-c\b|[\w./-]+\.py\b|scripts/)")

def validate_interpreter_paths(path: Path, text: str) -> list[str]:
    """Reject bare `python`/`python3` launchers; they are not on PATH (RC=127)."""
    errors: list[str] = []
    for lineno, line in enumerate(text.splitlines(), 1):
        for match in BARE_PYTHON.finditer(line):
            errors.append(
                f"{path}:{lineno}: bare {match.group().strip()!r} launcher is not on PATH "
                f"(exits 127); use an absolute interpreter path such as {VENV_PYTHON}"
            )
    return errors

def validate_hook_file(path: Path, data: object) -> list[str]:
    """Check hook definitions for the failure modes that caused ENOENT."""
    errors: list[str] = []
    if not isinstance(data, dict) or "hooks" not in data:
        return errors  # not a hook definition file
    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        return [f"{path}: 'hooks' must be an object"]
    for event, entries in hooks.items():
        if event not in VALID_HOOK_EVENTS:
            errors.append(f"{path}: unknown hook event {event!r}")
        if not isinstance(entries, list):
            errors.append(f"{path}: {event} must be an array")
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                errors.append(f"{path}: {event} entry must be an object")
                continue
            if entry.get("type") != "command":
                errors.append(f"{path}: {event} entry needs type 'command'")
            command = str(entry.get("command", ""))
            cwd = str(entry.get("cwd", ""))
            if not command:
                errors.append(f"{path}: {event} entry missing command")
                continue
            for field, value in (("command", command), ("cwd", cwd)):
                if "${" in value:
                    errors.append(
                        f"{path}: {event} {field} contains an unexpanded variable "
                        f"({value!r}); the hook executor does not substitute it"
                    )
            for launcher in SHELL_LAUNCHERS:
                if launcher in command:
                    errors.append(f"{path}: {event} command must not use a shell launcher ({launcher!r})")
            if cwd:
                if not cwd.startswith("/"):
                    errors.append(f"{path}: {event} cwd must be absolute, got {cwd!r}")
                elif not Path(cwd).is_dir():
                    errors.append(f"{path}: {event} cwd does not exist: {cwd}")
            parts = command.split()
            interpreter = parts[0]
            if not interpreter.startswith("/"):
                errors.append(f"{path}: {event} interpreter must be an absolute path, got {interpreter!r}")
            elif not Path(interpreter).is_file():
                errors.append(f"{path}: {event} interpreter not found: {interpreter}")
            if len(parts) > 1:
                script = parts[1]
                if script.startswith("/") and not Path(script).is_file():
                    errors.append(f"{path}: {event} script not found: {script}")
                elif not script.startswith("/"):
                    errors.append(f"{path}: {event} script must be an absolute path, got {script!r}")
    return errors


def frontmatter(path: Path) -> tuple[dict[str, str], str | None]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return {}, "missing opening frontmatter delimiter"
    end = text.find("\n---\n", 4)
    if end < 0:
        return {}, "missing closing frontmatter delimiter"
    values: dict[str, str] = {}
    for lineno, line in enumerate(text[4:end].splitlines(), 2):
        if not line or line.lstrip().startswith("#") or line.startswith((" ", "-")):
            continue
        match = KEY.match(line)
        if not match:
            return {}, f"invalid frontmatter line {lineno}: {line}"
        key, value = match.group(1), line.split(":", 1)[1].strip()
        if not value and key not in {"handoffs", "hooks"}:
            return {}, f"empty value for {key} at line {lineno}"
        values[key] = value
    return values, None


def validate(path: Path) -> list[str]:
    errors: list[str] = []
    if path.suffix == ".json":
        raw = path.read_text(encoding="utf-8")
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            errors.append(f"{path}: invalid JSON: {exc}")
        else:
            errors.extend(validate_hook_file(path, data))
            errors.extend(validate_interpreter_paths(path, raw))
        return errors
    if not path.name.endswith(VALID_SUFFIXES):
        return [f"{path}: unsupported customization suffix"]
    errors.extend(validate_interpreter_paths(path, path.read_text(encoding="utf-8")))
    values, error = frontmatter(path)
    if error: return errors + [f"{path}: {error}"]
    suffix = next(s for s in VALID_SUFFIXES if path.name.endswith(s))
    for required in REQUIRED.get(suffix, {"description"}):
        if required not in values: errors.append(f"{path}: missing required frontmatter key {required}")
    if not values.get("description", "").strip('"\' '): errors.append(f"{path}: blank description")
    return errors


def main() -> int:
    paths = [Path(item) for item in sys.argv[1:]]
    if not paths:
        paths = list(Path(".github").glob("**/*")) + list(Path.home().joinpath(".copilot/agents").glob("*.agent.md"))
    errors: list[str] = []
    for path in paths:
        if path.is_file(): errors.extend(validate(path))
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print(f"Customization validation PASS: {len([p for p in paths if p.is_file()])} file(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
