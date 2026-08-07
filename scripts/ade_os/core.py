"""Dependency-free ADE-OS v1 primitives; never a Core runtime dependency."""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping


class AdeError(RuntimeError):
    """Raised when ADE cannot safely establish a required fact."""


DEFAULT_ARTIFACT_ROOT = Path("/mnt/f/AIOS/anh-duong-checkpoints")
SCHEMA_VERSION = 1
SENSITIVE = re.compile(r"(?i)(authorization|bearer|api[_-]?key|token|oauth|password|secret)(\s*[:=]\s*)([^\s,;]+)")
ROUTES = (
    "closure", "review", "deep-debug", "terminal-exit", "provider-auth",
    "routing-blocked", "docker-mount", "media", "timeout-worker", "regression",
    "standard-fix", "diagnostic", "project-status",
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


def redact(value: str) -> str:
    return SENSITIVE.sub(r"\1\2<redacted>", value)


def redact_mapping(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "<redacted>" if re.search(r"(?i)(authorization|api[_-]?key|token|oauth|password|secret)", str(key)) else redact_mapping(item)
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
    allowed = {"runtime-memory", "active-checkpoint", "last-errors", "last-passed-tests", "deployment-history"}
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


def append_memory(root: Path, name: str, item: Mapping[str, Any], *, limit: int = 100) -> dict[str, Any]:
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
    role_patterns = {"roadmap": ("PROJECT.md", "STATE.md"), "changelog": ("CHANGELOG",), "spec": ("TASK_",), "checkpoint": ("CLOSED", "report", "rollback")}
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
                if any(part.startswith(".") or part == "__pycache__" for part in relative.parts) or path.suffix == ".pyc":
                    continue
            name = path.name
            role = next((key for key, patterns in role_patterns.items() if any(token in name for token in patterns)), "source")
            files[path.resolve()] = role
    return [{"canonical_path": str(path), "role": role, "timestamp": datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat(), "sha256": sha256(path)} for path, role in sorted(files.items(), key=lambda pair: str(pair[0]))]


def write_index(root: Path, *, check: bool = False) -> Path:
    destination = root / ".ade-os" / "generated" / "project-index.json"
    payload = {"version": SCHEMA_VERSION, "files": discover_index(root)}
    serialized = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if check:
        if not destination.exists():
            raise AdeError("project index is missing or stale")
        stored = load_json(destination).get("files", [])
        root_prefix = f"{root.resolve()}/"
        stored_workspace = [item for item in stored if str(item.get("canonical_path", "")).startswith(root_prefix)]
        current_workspace = [item for item in payload["files"] if item["canonical_path"].startswith(root_prefix)]
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
        title = next((line[2:].strip() for line in text.splitlines() if line.startswith("# ")), path.stem)
        records.append({"id": path.stem, "title": title, "path": str(path), "text": text})
    return records


def search_bugs(bugs_root: Path, query: str) -> list[dict[str, Any]]:
    tokens = tuple(re.findall(r"[\w-]+", query.lower()))
    matches = []
    for record in bug_records(bugs_root):
        haystack = f"{record['title']} {record['text']}".lower()
        score = sum(haystack.count(token) for token in tokens)
        if score:
            matches.append({"id": record["id"], "title": record["title"], "path": record["path"], "score": score})
    return sorted(matches, key=lambda item: (-item["score"], item["id"]))


def route_request(text: str, *, failed_repairs: int = 0, dirty_unknown: bool = False, destructive: bool = False) -> dict[str, Any]:
    normalized = " ".join(text.lower().split())
    if dirty_unknown:
        classification, reasons, conflict = "unknown", ["DIRTY_OWNERSHIP_UNKNOWN"], True
    elif destructive:
        classification, reasons, conflict = "standard-fix", ["DESTRUCTIVE_ACTION_REQUIRES_APPROVAL"], False
    elif failed_repairs >= 1:
        classification, reasons, conflict = "deep-debug", ["FAILED_REPAIR_ESCALATION"], False
    else:
        classification = next((route for route in ROUTES if any(key in normalized for key in KEYWORDS[route])), "unknown")
        reasons, conflict = [f"MATCH_{classification.upper().replace('-', '_')}"], False
    agent = {"project-status": "ad-project", "diagnostic": "ad-diagnose", "standard-fix": "ad-fix", "deep-debug": "ad-deep-debug", "review": "ad-review", "closure": "ad-orchestrator"}.get(classification, "ad-diagnose")
    combo = "vscode-review" if classification == "review" else "vscode-debug-deep" if classification == "deep-debug" else "vscode-debug"
    return {"classification": classification, "recommended_agent": agent, "recommended_prompt": f"ade-{classification}", "recommended_combo": combo, "reason_codes": reasons, "conflict": conflict, "requires_user_action": destructive, "next_gate": "resolve-conflict" if conflict else "review" if classification == "closure" else "diagnose"}


def checkpoint_gate(evidence: Mapping[str, Any], action: str) -> dict[str, Any]:
    required = ("conflict_gate", "scoped_diff", "tests", "backup", "rollback", "runtime_e2e")
    missing = [key for key in required if evidence.get(key) is not True]
    if action in {"review", "close"} and evidence.get("review") != "PASS":
        missing.insert(0, "review")
    return {"status": "PASS" if not missing else "BLOCKED", "missing": missing}
