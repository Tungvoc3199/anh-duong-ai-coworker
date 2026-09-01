#!/usr/bin/env python3
"""Fail-safe PreToolUse guard for destructive or out-of-scope commands."""

from __future__ import annotations

import json
import re
import shlex
import shutil
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ade_os import core

WRITE_TOOLS = {
    "write",
    "edit",
    "multiedit",
    "notebookedit",
    "create_file",
    "replace_string_in_file",
    "multi_replace_string_in_file",
    "insert_edit_into_file",
    "create_directory",
}
MUTATION_CAPABLE_TOOLS = WRITE_TOOLS | {
    "run_in_terminal",
    "runsubagent",
    "apply_patch",
    "bash",
    "send_to_terminal",
    "create_and_run_task",
    "kill_terminal",
}
TERMINAL_MUTATION_TOOLS = {
    "run_in_terminal",
    "bash",
    "send_to_terminal",
    "create_and_run_task",
}
PATCH_TOOLS = {"apply_patch"}
PATH_KEYS = {"file_path", "path", "notebook_path", "filePath", "dirPath", "notebookPath"}
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
APPROVED_EXACT_PATHS = frozenset({"tests/unit/test_ade_worktree_root_policy.py"})


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


def is_bootstrap_artifact_path(path: str, *, for_write: bool = False) -> bool:
    candidate = Path(path).resolve(strict=False)
    root = core.DEFAULT_ARTIFACT_ROOT.resolve(strict=False)
    if not core.is_relative_to(candidate, root):
        return False
    relative = candidate.relative_to(root)
    if len(relative.parts) != 2 or candidate.name not in {"start.json", "value-gate.json"}:
        return False
    return not (for_write and candidate.exists())


def is_bootstrap_checkpoint_directory(path: str) -> bool:
    candidate = Path(path).resolve(strict=False)
    root = core.DEFAULT_ARTIFACT_ROOT.resolve(strict=False)
    return candidate.parent == root and bool(
        re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", candidate.name)
    )


def terminal_command(payload: dict[str, Any]) -> str:
    value = tool_input(payload)
    if isinstance(value, dict) and isinstance(value.get("command"), str):
        return value["command"].strip()
    return ""


def is_bootstrap_mkdir_command(payload: dict[str, Any]) -> bool:
    if tool_name(payload) != "run_in_terminal":
        return False
    command = terminal_command(payload)
    if not command or any(marker in command for marker in ("&&", ";", "|", ">", "<", "\n", "\r")):
        return False
    try:
        tokens = shlex.split(command)
    except ValueError:
        return False
    return (
        len(tokens) == 3
        and tokens[0] == "mkdir"
        and tokens[1] in {"-p", "--parents"}
        and is_bootstrap_checkpoint_directory(tokens[2])
    )


def is_checkpoint_start_command(payload: dict[str, Any]) -> bool:
    if tool_name(payload) != "run_in_terminal":
        return False
    command = terminal_command(payload)
    if not command or any(marker in command for marker in ("&&", ";", "|", ">", "<", "\n", "\r")):
        return False
    try:
        tokens = shlex.split(command)
    except ValueError:
        return False
    interpreter = tokens[0]
    if (
        len(tokens) != 6
        or "/" in interpreter
        or "\\" in interpreter
        or not re.fullmatch(r"python(?:3(?:\.\d+)?)?", interpreter)
    ):
        return False
    resolved_interpreter = shutil.which(interpreter)
    if resolved_interpreter is None:
        return False
    try:
        trusted_interpreter = Path(resolved_interpreter).resolve(strict=True)
        guard_interpreter = Path(sys.executable).resolve(strict=True)
    except OSError:
        return False
    if trusted_interpreter != guard_interpreter:
        return False

    workspace = workspace_root(payload).resolve(strict=False)
    if core.validate_workspace(workspace, writable=True)["status"] != "ALLOW":
        return False
    script = Path(tokens[1])
    if not script.is_absolute():
        script = workspace / script
    expected_script = workspace / "scripts" / "ade_os.py"
    tail = tokens[2:]
    return (
        script.resolve(strict=False) == expected_script.resolve(strict=False)
        and tail[:3] == ["checkpoint", "start", "--evidence"]
        and len(tail) == 4
        and is_bootstrap_artifact_path(tail[3])
    )


def is_read_only_terminal_command(payload: dict[str, Any]) -> bool:
    if tool_name(payload) != "run_in_terminal":
        return False
    command = terminal_command(payload)
    if not command or any(marker in command for marker in ("&&", ";", "|", ">", "<", "\n", "\r")):
        return False
    try:
        tokens = shlex.split(command)
    except ValueError:
        return False
    if tokens == ["pwd"]:
        return True
    current = workspace_root(payload).resolve(strict=False)
    trusted_executable = _trusted_executable_from_token(tokens[0], current) if tokens else None
    if tokens and trusted_executable is not None and trusted_executable.name == "curl":
        safe_urls = {
            "http://127.0.0.1:8790/health",
            "http://127.0.0.1:8790/ready",
        }
        urls: list[str] = []
        index = 1
        while index < len(tokens):
            token = tokens[index]
            if token in {"--fail", "--silent", "--show-error"}:
                index += 1
                continue
            if token == "--max-time":
                if index + 1 >= len(tokens) or not re.fullmatch(
                    r"\d+(?:\.\d+)?", tokens[index + 1]
                ):
                    return False
                index += 2
                continue
            if re.fullmatch(r"-[fsS]+", token):
                index += 1
                continue
            if token.startswith("http://") or token.startswith("https://"):
                urls.append(token)
                index += 1
                continue
            return False
        return len(urls) == 1 and urls[0] in safe_urls
    safe_status_args = {
        "--short",
        "-s",
        "--branch",
        "-b",
        "--porcelain",
        "--porcelain=v1",
        "--porcelain=v2",
    }
    return (
        len(tokens) >= 2
        and trusted_executable is not None
        and trusted_executable.name == "git"
        and tokens[1] == "status"
        and all(arg in safe_status_args for arg in tokens[2:])
    )


def bypass_active_checkpoint(payload: dict[str, Any]) -> bool:
    name = tool_name(payload)
    if name in WRITE_TOOLS:
        paths = path_values(tool_input(payload))
        return bool(paths) and all(
            is_bootstrap_artifact_path(path, for_write=True) for path in paths
        )
    return (
        is_bootstrap_mkdir_command(payload)
        or is_checkpoint_start_command(payload)
        or is_read_only_terminal_command(payload)
    )


def workspace_root(payload: dict[str, Any]) -> Path:
    raw = payload.get("cwd")
    candidate = Path(str(raw)).resolve(strict=False) if raw else Path.cwd().resolve(strict=False)
    for current in (candidate, *candidate.parents):
        if (current / ".ade-os" / "project.yaml").exists():
            return current
    return Path(__file__).resolve().parents[2]


def resolved_target_path(payload: dict[str, Any], path: str) -> Path:
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = workspace_root(payload) / candidate
    return candidate.resolve(strict=False)


def target_workspace_for_path(payload: dict[str, Any], path: str) -> Path | None:
    resolved = resolved_target_path(payload, path)
    for root in (core.PRODUCTION_CORE_ROOT, core.CONTAINER_CORE_ROOT):
        root_resolved = root.resolve(strict=False)
        if resolved == root_resolved or core.is_relative_to(resolved, root_resolved):
            return root_resolved
    lane = core.core_worktree_lane_root_for(resolved)
    if lane is not None:
        return lane.resolve(strict=False)
    if not Path(path).is_absolute():
        return workspace_root(payload).resolve(strict=False)
    return None


def repo_relative(path: str, payload: dict[str, Any] | None = None) -> str:
    candidate = Path(path)
    if payload is not None and not candidate.is_absolute():
        resolved = (workspace_root(payload) / candidate).resolve(strict=False)
    else:
        resolved = candidate.resolve(strict=False)
    lane = core.core_worktree_lane_root_for(resolved)
    if lane is not None:
        return resolved.relative_to(lane.resolve(strict=False)).as_posix()
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
        if is_bootstrap_artifact_path(path, for_write=True):
            checks.append(core.decision("ALLOW", "BOOTSTRAP_ARTIFACT_OK", path=path))
            continue

        target_workspace = target_workspace_for_path(payload, path)
        current_workspace = workspace_root(payload).resolve(strict=False)
        if (
            target_workspace is not None
            and core.core_worktree_lane_root_for(target_workspace) is not None
            and target_workspace != current_workspace
        ):
            checks.append(
                core.decision(
                    "DENY",
                    "GOVERNANCE_FAILURE",
                    "WORKSPACE_MISMATCH",
                    workspace=str(current_workspace),
                    target_workspace=str(target_workspace),
                )
            )
        if target_workspace is not None:
            checks.append(core.validate_workspace(target_workspace, writable=True))
        relative = repo_relative(path, payload)
        if relative in APPROVED_EXACT_PATHS:
            checks.append(core.decision("ALLOW", "SCOPE_OK", checked=[relative]))
        else:
            checks.append(
                core.validate_changed_paths(
                    [relative],
                    allowed_paths=list(APPROVED_ALLOWED_PATHS),
                )
            )
    return checks


def mutation_workspace_roots(payload: dict[str, Any]) -> list[Path]:
    if tool_name(payload) not in WRITE_TOOLS:
        return [workspace_root(payload).resolve(strict=False)]
    roots: list[Path] = []
    for path in path_values(tool_input(payload)):
        if is_bootstrap_artifact_path(path, for_write=True):
            continue
        target = target_workspace_for_path(payload, path)
        if target is None or target in {
            core.PRODUCTION_CORE_ROOT.resolve(strict=False),
            core.CONTAINER_CORE_ROOT.resolve(strict=False),
        }:
            continue
        if core.core_worktree_lane_root_for(target) is not None and target not in roots:
            roots.append(target)
    return roots or [workspace_root(payload).resolve(strict=False)]


def _workspace_scope_denial(
    current: Path,
    *,
    path: str | None = None,
    detail: str | None = None,
) -> dict[str, Any]:
    extra: dict[str, Any] = {"workspace": str(current)}
    if path is not None:
        extra["path"] = path
    if detail is not None:
        extra["detail"] = detail
    return core.decision(
        "DENY",
        "SCOPE_FAILURE",
        "WORKSPACE_SCOPE_FAILURE",
        **extra,
    )


def _trusted_absolute_executable(path: Path, current: Path) -> bool:
    resolved = path.resolve(strict=False)
    trusted_roots = (
        Path("/usr/bin").resolve(strict=False),
        Path("/bin").resolve(strict=False),
        (core.PRODUCTION_CORE_ROOT / ".venv" / "bin").resolve(strict=False),
    )
    return any(core.is_relative_to(resolved, root) for root in trusted_roots)


def _trusted_executable_from_token(token: str, current: Path) -> Path | None:
    candidate = Path(token)
    if candidate.is_absolute():
        resolved = candidate.resolve(strict=False)
    elif "/" in token or token.startswith("."):
        resolved = (current / candidate).resolve(strict=False)
    else:
        located = shutil.which(token)
        if located is None:
            return None
        resolved = Path(located).resolve(strict=False)
    if not _trusted_absolute_executable(resolved, current):
        return None
    return resolved


def _path_candidate_from_token(token: str, current: Path) -> Path | None:
    if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*://", token):
        return None
    value = token.split("=", 1)[1] if "=" in token and token.startswith("-") else token
    value = value.rstrip(",:")
    if not value or value in {".", ".."}:
        return (current / value).resolve(strict=False) if value else None
    candidate = Path(value)
    if candidate.is_absolute():
        return candidate.resolve(strict=False)
    if "/" in value or value.startswith("."):
        return (current / candidate).resolve(strict=False)
    return None


def terminal_target_checks(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if tool_name(payload) not in TERMINAL_MUTATION_TOOLS:
        return []
    current = workspace_root(payload).resolve(strict=False)
    checks = [core.validate_workspace(current, writable=True)]
    command = text_from(tool_input(payload))
    try:
        tokens = shlex.split(command)
    except ValueError:
        checks.append(_workspace_scope_denial(current, detail="unparseable shell command"))
        return checks
    if not tokens:
        checks.append(_workspace_scope_denial(current, detail="empty shell command"))
        return checks

    shell_operators = ("&&", "||", ";", "|", ">", "<", "\n", "\r", "`", "$(")
    if any(operator in command for operator in shell_operators):
        checks.append(
            _workspace_scope_denial(current, detail="compound shell syntax is not allowed")
        )
        return checks

    command_index = 0
    while command_index < len(tokens) and re.fullmatch(
        r"[A-Za-z_][A-Za-z0-9_]*=.*", tokens[command_index]
    ):
        command_index += 1
    if command_index >= len(tokens):
        checks.append(
            _workspace_scope_denial(current, detail="environment assignment has no command")
        )
        return checks
    safe_environment_names = {
        "CI",
        "LANG",
        "LC_ALL",
        "NO_COLOR",
        "PYTHONDONTWRITEBYTECODE",
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD",
        "TZ",
    }
    for assignment in tokens[:command_index]:
        name = assignment.split("=", 1)[0]
        if name not in safe_environment_names:
            checks.append(
                _workspace_scope_denial(
                    current,
                    detail=f"environment assignment {name} can alter command resolution",
                )
            )
            return checks
    tokens = tokens[command_index:]

    normalized_tokens = " ".join(tokens)
    if (
        ".local/state/ade-os" in normalized_tokens
        or "$" in command
        or any(token.startswith("~") for token in tokens)
    ):
        checks.append(
            _workspace_scope_denial(
                current,
                detail="home expansion or ADE state path is not a terminal mutation target",
            )
        )
        return checks

    trusted_executable = _trusted_executable_from_token(tokens[0], current)
    if trusted_executable is None:
        checks.append(
            _workspace_scope_denial(
                current,
                path=tokens[0],
                detail="executable does not resolve to a trusted system binary",
            )
        )
        return checks
    executable_name = Path(tokens[0]).name
    if executable_name in {
        "docker",
        "podman",
        "kubectl",
        "ssh",
        "scp",
        "rsync",
        "wsl",
        "wsl.exe",
        "env",
        "command",
        "nice",
        "nohup",
        "timeout",
        "sudo",
        "xargs",
        "make",
        "ninja",
        "npm",
        "pnpm",
        "yarn",
        "poetry",
        "tox",
        "nox",
        "uv",
        "pip",
        "pip3",
        "curl",
        "wget",
        "http",
        "httpie",
        "gh",
        "glab",
        "aws",
        "gcloud",
        "az",
        "nc",
        "netcat",
        "socat",
        "ftp",
        "sftp",
    }:
        checks.append(
            _workspace_scope_denial(
                current, detail="external or container execution is not scope-auditable"
            )
        )
        return checks

    if executable_name == "find" and any(
        token in {"-exec", "-execdir"} or token.startswith("-exec")
        for token in tokens[1:]
    ):
        checks.append(
            _workspace_scope_denial(
                current, detail="find execution hooks are not scope-auditable"
            )
        )
        return checks

    if executable_name.startswith("python") and "-m" in tokens[1:]:
        module_index = tokens.index("-m", 1)
        module = tokens[module_index + 1] if module_index + 1 < len(tokens) else ""
        try:
            guard_interpreter = Path(sys.executable).resolve(strict=True)
        except OSError:
            guard_interpreter = Path(sys.executable).resolve(strict=False)
        isolated = "-I" in tokens[1:module_index]
        if (
            module not in {"pytest", "compileall"}
            or not isolated
            or trusted_executable != guard_interpreter
        ):
            checks.append(
                _workspace_scope_denial(
                    current,
                    detail="Python module execution requires the trusted isolated interpreter",
                )
            )
            return checks

    if executable_name == "git":
        dangerous_git_options = {"-c", "--config-env", "--exec-path"}
        for token in tokens[1:]:
            if (
                token in dangerous_git_options
                or token.startswith("-c") and token != "-C"
                or token.startswith("--config-env=")
                or token.startswith("--exec-path=")
            ):
                checks.append(
                    _workspace_scope_denial(
                        current, detail="Git command-extension/config injection is not allowed"
                    )
                )
                return checks

        redirected: list[str] = []
        index = 1
        while index < len(tokens):
            token = tokens[index]
            if token == "-C" and index + 1 < len(tokens):
                redirected.append(tokens[index + 1])
                index += 2
                continue
            if token.startswith("-C") and token != "-C":
                redirected.append(token[2:])
            elif token in {"--git-dir", "--work-tree"} and index + 1 < len(tokens):
                redirected.append(tokens[index + 1])
                index += 2
                continue
            elif token.startswith("--git-dir=") or token.startswith("--work-tree="):
                redirected.append(token.split("=", 1)[1])
            index += 1
        for redirected_path in redirected:
            candidate = _path_candidate_from_token(redirected_path, current)
            if candidate is None or not core.is_relative_to(candidate, current):
                checks.append(
                    _workspace_scope_denial(
                        current,
                        path=str(candidate) if candidate is not None else redirected_path,
                        detail="git repository redirection escapes active workspace",
                    )
                )
                return checks

        allowed_git_subcommands = {
            "add",
            "branch",
            "cat-file",
            "cherry-pick",
            "commit",
            "diff",
            "diff-tree",
            "for-each-ref",
            "log",
            "ls-files",
            "merge",
            "merge-base",
            "rebase",
            "remote",
            "reset",
            "restore",
            "rev-parse",
            "show",
            "stash",
            "status",
            "worktree",
        }
        subcommand: str | None = None
        subcommand_index: int | None = None
        index = 1
        while index < len(tokens):
            token = tokens[index]
            if token == "-C" or token in {"--git-dir", "--work-tree"}:
                index += 2
                continue
            if token.startswith("-C") and token != "-C":
                index += 1
                continue
            if token.startswith("--git-dir=") or token.startswith("--work-tree="):
                index += 1
                continue
            if token.startswith("-"):
                index += 1
                continue
            subcommand = token
            subcommand_index = index
            break
        if subcommand not in allowed_git_subcommands or subcommand_index is None:
            checks.append(
                _workspace_scope_denial(
                    current, detail="Git subcommand is outside the governed builtin allowlist"
                )
            )
            return checks

        git_args = tokens[subcommand_index + 1 :]
        if subcommand == "remote":
            remote_query_ok = (
                git_args in ([], ["-v"])
                or (len(git_args) >= 2 and git_args[0] == "get-url")
            )
            if not remote_query_ok:
                checks.append(
                    _workspace_scope_denial(
                        current, detail="Git remote mutation is owner/operator-only"
                    )
                )
                return checks
        elif subcommand == "branch":
            if git_args not in ([], ["--show-current"], ["--list"]):
                checks.append(
                    _workspace_scope_denial(
                        current, detail="Git branch mutation is outside active-worktree scope"
                    )
                )
                return checks
        elif subcommand == "worktree":
            if not (
                git_args
                and git_args[0] == "list"
                and all(arg in {"--porcelain", "-z", "-v"} for arg in git_args[1:])
            ):
                checks.append(
                    _workspace_scope_denial(
                        current, detail="Git worktree mutation is owner/operator-only"
                    )
                )
                return checks

    workspace_executable = _path_candidate_from_token(tokens[0], current)
    if ("/" in tokens[0] or tokens[0].startswith(".")) and (
        workspace_executable is not None
        and core.is_relative_to(workspace_executable, current)
    ):
        checks.append(
            _workspace_scope_denial(
                current,
                path=str(workspace_executable),
                detail="workspace-controlled executable is not scope-auditable",
            )
        )
        return checks

    script_interpreters = {
        "python",
        "python3",
        "python3.12",
        "bash",
        "sh",
        "zsh",
        "node",
        "perl",
        "ruby",
    }
    if executable_name in script_interpreters and "-c" not in tokens[1:]:
        if not (
            executable_name.startswith("python")
            and len(tokens) >= 3
            and tokens[1] == "-m"
        ):
            for token in tokens[1:]:
                if token == "--":
                    continue
                if token.startswith("-"):
                    continue
                script_candidate = _path_candidate_from_token(token, current)
                if script_candidate is not None and core.is_relative_to(
                    script_candidate, current
                ):
                    checks.append(
                        _workspace_scope_denial(
                            current,
                            path=str(script_candidate),
                            detail="workspace-controlled script is not scope-auditable",
                        )
                    )
                    return checks
                break

    inline_eval_flags = {
        "python": {"-c"},
        "python3": {"-c"},
        "python3.12": {"-c"},
        "bash": {"-c"},
        "sh": {"-c"},
        "zsh": {"-c"},
        "node": {"-e", "--eval"},
        "perl": {"-e"},
        "ruby": {"-e"},
    }
    if any(flag in tokens[1:] for flag in inline_eval_flags.get(executable_name, set())):
        checks.append(
            _workspace_scope_denial(
                current, detail="inline executable code is not scope-auditable"
            )
        )
        return checks

    artifact_root = core.DEFAULT_ARTIFACT_ROOT.resolve(strict=False)
    executable = trusted_executable

    for index, token in enumerate(tokens):
        if index == 0 and executable.is_absolute():
            continue
        if token.startswith("-") and "=" not in token:
            continue
        candidate = _path_candidate_from_token(token, current)
        if candidate is None:
            continue
        if candidate == Path("/dev/null"):
            continue
        if core.is_relative_to(candidate, current):
            continue
        if core.is_relative_to(candidate, artifact_root):
            continue
        checks.append(_workspace_scope_denial(current, path=str(candidate)))

    absolute_path_pattern = r"(?:^|[\s'\"(=])(/(?!/)[^\s'\";|><)]+)"
    for match in re.finditer(absolute_path_pattern, command):
        candidate = Path(match.group(1)).resolve(strict=False)
        if executable.is_absolute() and candidate == executable.resolve(strict=False):
            continue
        if candidate == Path("/dev/null"):
            continue
        if core.is_relative_to(candidate, current) or core.is_relative_to(candidate, artifact_root):
            continue
        checks.append(_workspace_scope_denial(current, path=str(candidate)))
    return checks


def patch_paths(payload: dict[str, Any]) -> list[str]:
    if tool_name(payload) not in PATCH_TOOLS:
        return []
    value = tool_input(payload)
    patch = value.get("patch") if isinstance(value, dict) else None
    if not isinstance(patch, str):
        return []
    found: list[str] = []
    for line in patch.splitlines():
        match = re.match(r"^\*\*\* (?:Update|Add|Delete) File:\s*(.+?)\s*$", line)
        if match:
            found.append(match.group(1))
            continue
        match = re.match(r"^\*\*\* Move to:\s*(.+?)\s*$", line)
        if match:
            found.append(match.group(1))
            continue
        match = re.match(r"^(?:---|\+\+\+)\s+(?:[ab]/)?(.+?)\s*$", line)
        if match and match.group(1) != "/dev/null":
            found.append(match.group(1))
    return list(dict.fromkeys(found))


def inferred_patch_checks(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if tool_name(payload) not in PATCH_TOOLS:
        return []
    paths = patch_paths(payload)
    if not paths:
        return [
            core.decision(
                "DENY",
                "SCOPE_FAILURE",
                "SCOPE_VIOLATION",
                violations=["apply_patch payload has no auditable target path"],
            )
        ]
    checks: list[dict[str, Any]] = []
    current = workspace_root(payload).resolve(strict=False)
    for path in paths:
        target = target_workspace_for_path(payload, path)
        if target is None:
            checks.append(
                core.decision(
                    "DENY",
                    "SCOPE_FAILURE",
                    "SCOPE_VIOLATION",
                    violations=[path],
                )
            )
            continue
        if target != current:
            checks.append(
                core.decision(
                    "DENY",
                    "GOVERNANCE_FAILURE",
                    "WORKSPACE_MISMATCH",
                    workspace=str(current),
                    target_workspace=str(target),
                )
            )
        checks.append(core.validate_workspace(target, writable=True))
        relative = repo_relative(path, payload)
        if relative in APPROVED_EXACT_PATHS:
            checks.append(core.decision("ALLOW", "SCOPE_OK", checked=[relative]))
        else:
            checks.append(
                core.validate_changed_paths(
                    [relative],
                    allowed_paths=list(APPROVED_ALLOWED_PATHS),
                )
            )
    return checks


def governance_checks(payload: dict[str, Any]) -> list[dict[str, Any]]:
    metadata = payload.get("ade_governance")
    checks = [*inferred_write_checks(payload), *inferred_patch_checks(payload)]
    bypass = bypass_active_checkpoint(payload)
    if tool_name(payload) in MUTATION_CAPABLE_TOOLS and not bypass:
        for root in mutation_workspace_roots(payload):
            checks.append(core.validate_active_checkpoint_for_mutation(root))
        checks.extend(terminal_target_checks(payload))
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
