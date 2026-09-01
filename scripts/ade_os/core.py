"""Dependency-free ADE-OS v1 primitives; never a Core runtime dependency."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class AdeError(RuntimeError):
    """Raised when ADE cannot safely establish a required fact."""


DEFAULT_ARTIFACT_ROOT = Path("/mnt/f/AIOS/anh-duong-checkpoints")
SCHEMA_VERSION = 1
PRODUCTION_CORE_ROOT = Path("/home/thadc/AIOS/anh-duong-core")
CONTAINER_CORE_ROOT = Path("/workspaces/anh-duong-core")
CORE_WORKTREE_ROOT = Path("/home/thadc/AIOS/worktrees")
LEGACY_CORE_WORKTREE_ROOT = Path("/home/thadc/AIOS/anh-duong-core.worktrees")
CORE_WORKTREE_ROOTS = (CORE_WORKTREE_ROOT, LEGACY_CORE_WORKTREE_ROOT)
OPENCLAW_ROOT = Path("/home/thadc/AIOS/openclaw")
RUNTIME_DB = Path("/home/thadc/.local/state/anh-duong-core/anh_duong.db")
FAILURE_CLASSES = (
    "DELTA_FAILURE",
    "PRE_EXISTING_FAILURE",
    "ENVIRONMENT_FAILURE",
    "SCOPE_FAILURE",
    "GOVERNANCE_FAILURE",
)
REQUIRED_TASK_MANIFEST = {
    "checkpoint_id": str,
    "code_change": bool,
    "production_write": bool,
    "service_restart": bool,
    "database_write": bool,
    "config_write": bool,
    "push": bool,
    "main_merge": bool,
    "max_semantic_repair_rounds": int,
    "artifact_inside_repo": bool,
}
FORBIDDEN_TRUE_MANIFEST_FLAGS = (
    "production_write",
    "service_restart",
    "database_write",
    "config_write",
    "push",
    "main_merge",
    "artifact_inside_repo",
)
RELEASE_GATES = (
    "conflict_gate",
    "scoped_diff",
    "tests",
    "backup",
    "rollback",
    "runtime_e2e",
)
SENSITIVE = re.compile(
    r"(?i)(authorization|bearer|api[_-]?key|token|oauth|password|secret)(\s*[:=]\s*)([^\s,;]+)"
)
ROUTES = (
    "closure",
    "review",
    "deep-debug",
    "terminal-exit",
    "provider-auth",
    "routing-blocked",
    "docker-mount",
    "media",
    "timeout-worker",
    "regression",
    "standard-fix",
    "diagnostic",
    "project-status",
)
KEYWORDS = {
    "closure": ("close", "closure", "complete checkpoint"),
    "review": ("review", "audit", "verify diff"),
    "deep-debug": ("deep debug", "race", "nondeterministic", "multi-layer"),
    "terminal-exit": ("exit code", "command not found", "127"),
    "provider-auth": ("provider", "quota", "429", "authentication", "auth"),
    "routing-blocked": ("blocked", "safe message", "routing"),
    "docker-mount": ("docker", "wsl", "mount"),
    "media": ("image", "media", "vision", "telegram image"),
    "timeout-worker": ("timeout", "worker", "lease"),
    "regression": ("regression", "previously passed"),
    "standard-fix": ("fix", "repair", "implement", "change"),
    "diagnostic": ("diagnose", "diagnostic", "investigate", "why", "failure", "error", "lỗi"),
    "project-status": ("project status", "status", "roadmap", "checkpoint"),
}


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def utc_suffix() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def decision(status: str, reason: str, code: str | None = None, **extra: Any) -> dict[str, Any]:
    result = {"status": status, "reason": reason}
    if code:
        result["code"] = code
    result.update(extra)
    return result


def redact(value: str) -> str:
    return SENSITIVE.sub(r"\1\2<redacted>", value)


def redact_mapping(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "<redacted>"
            if re.search(r"(?i)(authorization|api[_-]?key|token|oauth|password|secret)", str(key))
            else redact_mapping(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_mapping(item) for item in value]
    return redact(value) if isinstance(value, str) else value


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise AdeError(f"cannot load configuration {path}: {error}") from error
    if not isinstance(value, dict):
        raise AdeError(f"configuration {path} must be an object")
    return value


def is_relative_to(path: Path, base: Path) -> bool:
    try:
        path.relative_to(base)
    except ValueError:
        return False
    return True


def core_worktree_root_for(path: Path) -> Path | None:
    resolved = path.resolve(strict=False)
    return next((root for root in CORE_WORKTREE_ROOTS if is_relative_to(resolved, root)), None)


def validate_workspace(root: Path, *, writable: bool) -> dict[str, Any]:
    resolved = root.resolve(strict=False)
    if writable and resolved in {PRODUCTION_CORE_ROOT, CONTAINER_CORE_ROOT}:
        return decision("DENY", "GOVERNANCE_FAILURE", workspace=str(resolved))
    if not writable:
        return decision(
            "ALLOW", "GOVERNANCE_OK", workspace=str(resolved), workspace_kind="read_only"
        )
    if core_worktree_root_for(resolved) is None:
        return decision("DENY", "GOVERNANCE_FAILURE", workspace=str(resolved))
    git_file = resolved / ".git"
    try:
        git_text = git_file.read_text(encoding="utf-8")
    except OSError:
        return decision("DENY", "GOVERNANCE_FAILURE", workspace=str(resolved))
    if f"{PRODUCTION_CORE_ROOT}/.git/worktrees/" not in git_text:
        return decision("DENY", "GOVERNANCE_FAILURE", workspace=str(resolved))
    return decision(
        "ALLOW", "GOVERNANCE_OK", workspace=str(resolved), workspace_kind="isolated_worktree"
    )


def normalize_repo_path(path: str) -> str:
    normalized = Path(path)
    if normalized.is_absolute() or ".." in normalized.parts:
        raise AdeError("changed path escapes repository")
    return normalized.as_posix().lstrip("./")


def path_allowed(path: str, allowed_paths: list[str]) -> bool:
    return any(
        path == allowed.rstrip("/") or path.startswith(f"{allowed.rstrip('/')}/")
        for allowed in allowed_paths
    )


def validate_changed_paths(changed_paths: list[str], *, allowed_paths: list[str]) -> dict[str, Any]:
    if not allowed_paths:
        return decision("DENY", "SCOPE_FAILURE", "SCOPE_VIOLATION", violations=changed_paths)
    violations: list[str] = []
    for raw in changed_paths:
        try:
            normalized = normalize_repo_path(raw)
        except AdeError:
            violations.append(raw)
            continue
        if not path_allowed(normalized, allowed_paths):
            violations.append(normalized)
    if violations:
        return decision("DENY", "SCOPE_FAILURE", "SCOPE_VIOLATION", violations=violations)
    return decision("ALLOW", "SCOPE_OK", checked=changed_paths)


def validate_task_manifest(path: Path, *, checkpoint_id: str) -> dict[str, Any]:
    try:
        payload = load_json(path)
    except AdeError as error:
        return decision("DENY", "GOVERNANCE_FAILURE", error=str(error))
    missing = [key for key in REQUIRED_TASK_MANIFEST if key not in payload]
    wrong_type = [
        key
        for key, expected in REQUIRED_TASK_MANIFEST.items()
        if key in payload and not isinstance(payload[key], expected)
    ]
    forbidden = [key for key in FORBIDDEN_TRUE_MANIFEST_FLAGS if payload.get(key) is True]
    if payload.get("checkpoint_id") != checkpoint_id:
        forbidden.append("checkpoint_id")
    if payload.get("max_semantic_repair_rounds") != 2:
        forbidden.append("max_semantic_repair_rounds")
    if missing or wrong_type or forbidden:
        return decision(
            "DENY",
            "GOVERNANCE_FAILURE",
            missing=missing,
            wrong_type=wrong_type,
            forbidden=forbidden,
        )
    return decision("ALLOW", "GOVERNANCE_OK", checkpoint_id=checkpoint_id)


def validate_role_capability(role: str, capability: str) -> dict[str, Any]:
    if role == "reviewer" and capability in {"write", "repair", "edit", "mutate"}:
        return decision("DENY", "GOVERNANCE_FAILURE", role=role, capability=capability)
    return decision("ALLOW", "GOVERNANCE_OK", role=role, capability=capability)


def validate_semantic_repair(
    failure_class: str, *, repair_round: int, max_rounds: int = 2
) -> dict[str, Any]:
    if failure_class not in FAILURE_CLASSES:
        return decision("DENY", "GOVERNANCE_FAILURE", failure_class=failure_class)
    if failure_class != "DELTA_FAILURE":
        return decision("DENY", "GOVERNANCE_FAILURE", failure_class=failure_class)
    if repair_round > max_rounds or max_rounds > 2:
        return decision(
            "DENY", "GOVERNANCE_FAILURE", failure_class=failure_class, repair_round=repair_round
        )
    return decision(
        "ALLOW", "GOVERNANCE_OK", failure_class=failure_class, repair_round=repair_round
    )


@dataclass
class ResultContract:
    fields: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> ResultContract:
        required = {
            "checkpoint_id",
            "status",
            "classification",
            "artifacts",
            "production_write",
            "service_restart",
            "database_write",
            "release_ready",
        }
        missing = sorted(required.difference(payload))
        if missing:
            raise AdeError(f"result contract missing critical fields: {', '.join(missing)}")
        return cls(dict(payload))

    def to_mapping(self) -> dict[str, Any]:
        return dict(self.fields)


def evaluate_release_gate(evidence: Mapping[str, Any], *, approved: bool) -> dict[str, Any]:
    missing = [gate for gate in RELEASE_GATES if evidence.get(gate) is not True]
    review_pass = evidence.get("review") == "PASS"
    release_ready = not missing and review_pass and approved
    return {
        "release_ready": release_ready,
        "performed_release": False,
        "missing": missing,
        "review_pass": review_pass,
        "approved": approved,
    }


def runtime_truth(env: Mapping[str, str | None]) -> dict[str, Any]:
    redacted: dict[str, str | None] = {}
    for key, value in sorted(env.items()):
        if re.search(r"(?i)(authorization|api[_-]?key|token|oauth|password|secret)", key):
            redacted[key] = "PRESENT" if value else "MISSING"
        else:
            redacted[key] = value
    return {
        "schema_version": SCHEMA_VERSION,
        "production_paths": {
            "core": str(PRODUCTION_CORE_ROOT),
            "openclaw": str(OPENCLAW_ROOT),
            "core_worktrees": str(CORE_WORKTREE_ROOT),
            "db": str(RUNTIME_DB),
            "checkpoint_root": str(DEFAULT_ARTIFACT_ROOT),
        },
        "env": redacted,
    }


def ownership_matrix() -> dict[str, Any]:
    return {
        "core": {"path": str(PRODUCTION_CORE_ROOT), "role": "canonical brain/governance"},
        "openclaw": {"path": str(OPENCLAW_ROOT), "role": "channel/execution/delivery"},
        "9router": {"path": None, "role": "provider/model router"},
        "ade_os": {"path": ".ade-os", "role": "engineering governance/control"},
    }


def project_config(root: Path) -> dict[str, Any]:
    config = load_json(root / ".ade-os" / "project.yaml")
    if config.get("version") != SCHEMA_VERSION:
        raise AdeError("unsupported ADE project configuration version")
    return config


def state_root(root: Path) -> Path:
    digest = hashlib.sha256(str(root.resolve()).encode()).hexdigest()[:16]
    return Path.home() / ".local" / "state" / "ade-os" / digest


def atomic_write(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def memory_file(root: Path, name: str) -> Path:
    allowed = {
        "runtime-memory",
        "active-checkpoint",
        "last-errors",
        "last-passed-tests",
        "deployment-history",
    }
    if name not in allowed:
        raise AdeError("unsupported memory record")
    return state_root(root) / f"{name}.json"


def read_memory(root: Path, name: str) -> dict[str, Any]:
    path = memory_file(root, name)
    if not path.exists():
        return {"version": SCHEMA_VERSION, "updated_at": utc_now(), "items": []}
    try:
        loaded = load_json(path)
    except AdeError:
        quarantine = path.with_name(f"{path.name}.corrupt-{utc_suffix()}")
        try:
            path.replace(quarantine)
        except OSError:
            pass
        return {"version": SCHEMA_VERSION, "updated_at": utc_now(), "items": []}
    if loaded.get("version") != SCHEMA_VERSION:
        raise AdeError("unsupported runtime memory version")
    return loaded


def append_memory(
    root: Path, name: str, item: Mapping[str, Any], *, limit: int = 100
) -> dict[str, Any]:
    record = read_memory(root, name)
    items = record.get("items", [])
    if not isinstance(items, list):
        items = []
    clean = redact_mapping(dict(item))
    items.append({"recorded_at": utc_now(), **clean})
    result = {"version": SCHEMA_VERSION, "updated_at": utc_now(), "items": items[-limit:]}
    atomic_write(memory_file(root, name), result)
    return result


def artifact_directory(config: Mapping[str, Any], root: Path) -> Path:
    candidate = Path(str(config.get("artifact_path", DEFAULT_ARTIFACT_ROOT)))
    try:
        candidate.mkdir(parents=True, exist_ok=True)
        return candidate
    except OSError:
        fallback = state_root(root) / "pending-artifacts"
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


def discover_index(root: Path) -> list[dict[str, str]]:
    role_patterns = {
        "roadmap": ("PROJECT.md", "STATE.md"),
        "changelog": ("CHANGELOG",),
        "spec": ("TASK_",),
        "checkpoint": ("CLOSED", "report", "rollback"),
    }
    files: dict[Path, str] = {}
    search_roots = [root, Path("/mnt/f/AIOS/anh-duong-checkpoints")]
    for base in search_roots:
        if not base.exists():
            continue
        iterator = base.rglob("*") if base == root else base.glob("*")
        for path in iterator:
            if not path.is_file():
                continue
            if base == root:
                relative = path.relative_to(root)
                if (
                    any(part.startswith(".") or part == "__pycache__" for part in relative.parts)
                    or path.suffix == ".pyc"
                ):
                    continue
            name = path.name
            role = next(
                (
                    key
                    for key, patterns in role_patterns.items()
                    if any(token in name for token in patterns)
                ),
                "source",
            )
            files[path.resolve()] = role
    return [
        {
            "canonical_path": str(path),
            "role": role,
            "timestamp": datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat(),
            "sha256": sha256(path),
        }
        for path, role in sorted(files.items(), key=lambda pair: str(pair[0]))
    ]


def write_index(root: Path, *, check: bool = False) -> Path:
    destination = root / ".ade-os" / "generated" / "project-index.json"
    files = discover_index(root)
    payload: dict[str, Any] = {"version": SCHEMA_VERSION, "files": files}
    serialized = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if check:
        if not destination.exists():
            raise AdeError("project index is missing or stale")
        stored = load_json(destination).get("files", [])
        root_prefix = f"{root.resolve()}/"
        stored_workspace = [
            item for item in stored if str(item.get("canonical_path", "")).startswith(root_prefix)
        ]
        current_workspace = [
            item for item in files if item["canonical_path"].startswith(root_prefix)
        ]
        if stored_workspace != current_workspace:
            raise AdeError("project index is missing or stale")
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(serialized, encoding="utf-8")
    return destination


def bug_records(bugs_root: Path) -> list[dict[str, str]]:
    records = []
    for path in sorted(bugs_root.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        title = next(
            (line[2:].strip() for line in text.splitlines() if line.startswith("# ")), path.stem
        )
        records.append({"id": path.stem, "title": title, "path": str(path), "text": text})
    return records


def search_bugs(bugs_root: Path, query: str) -> list[dict[str, Any]]:
    tokens = tuple(re.findall(r"[\w-]+", query.lower()))
    matches = []
    for record in bug_records(bugs_root):
        haystack = f"{record['title']} {record['text']}".lower()
        score = sum(haystack.count(token) for token in tokens)
        if score:
            matches.append(
                {
                    "id": record["id"],
                    "title": record["title"],
                    "path": record["path"],
                    "score": score,
                }
            )
    return sorted(matches, key=lambda item: (-item["score"], item["id"]))


def route_request(
    text: str, *, failed_repairs: int = 0, dirty_unknown: bool = False, destructive: bool = False
) -> dict[str, Any]:
    normalized = " ".join(text.lower().split())
    if dirty_unknown:
        classification, reasons, conflict = "unknown", ["DIRTY_OWNERSHIP_UNKNOWN"], True
    elif destructive:
        classification, reasons, conflict = (
            "standard-fix",
            ["DESTRUCTIVE_ACTION_REQUIRES_APPROVAL"],
            False,
        )
    elif failed_repairs >= 1:
        classification, reasons, conflict = "deep-debug", ["FAILED_REPAIR_ESCALATION"], False
    else:
        classification = next(
            (route for route in ROUTES if any(key in normalized for key in KEYWORDS[route])),
            "unknown",
        )
        reasons, conflict = [f"MATCH_{classification.upper().replace('-', '_')}"], False
    agent = {
        "project-status": "ad-project",
        "diagnostic": "ad-diagnose",
        "standard-fix": "ad-fix",
        "deep-debug": "ad-deep-debug",
        "review": "ad-review",
        "closure": "ad-orchestrator",
    }.get(classification, "ad-diagnose")
    combo = (
        "vscode-review"
        if classification == "review"
        else "vscode-debug-deep"
        if classification == "deep-debug"
        else "vscode-debug"
    )
    return {
        "classification": classification,
        "recommended_agent": agent,
        "recommended_prompt": f"ade-{classification}",
        "recommended_combo": combo,
        "reason_codes": reasons,
        "conflict": conflict,
        "requires_user_action": destructive,
        "next_gate": "resolve-conflict"
        if conflict
        else "review"
        if classification == "closure"
        else "diagnose",
    }


def checkpoint_gate(evidence: Mapping[str, Any], action: str) -> dict[str, Any]:
    required = ("conflict_gate", "scoped_diff", "tests", "backup", "rollback", "runtime_e2e")
    missing = [key for key in required if evidence.get(key) is not True]
    if action in {"review", "close"} and evidence.get("review") != "PASS":
        missing.insert(0, "review")
    return {"status": "PASS" if not missing else "BLOCKED", "missing": missing}
