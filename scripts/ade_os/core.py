"""Dependency-free ADE-OS v1 primitives; never a Core runtime dependency."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
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
NATIVE_CAPABILITY_DECISIONS = (
    "USE_NATIVE",
    "WRAP_NATIVE",
    "EXTEND_NATIVE",
    "BUILD_CUSTOM",
)
CHECKPOINT_WORK_TYPES = (
    "feature",
    "automation",
    "integration",
    "custom_build",
    "repair",
    "diagnostic",
    "security",
    "compliance",
    "maintenance",
)
VALUE_GATED_WORK_TYPES = frozenset({"feature", "automation", "integration", "custom_build"})
CLOSURE_REVIEW_PROTOCOL_VERSION = 1
CLOSURE_REVIEW_MAX_SEMANTIC_ROUNDS = 2
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


def resolve_repository_head(root: Path) -> str | None:
    """Resolve the repository HEAD used to bind closure evidence."""
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--verify", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
            timeout=3,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    head = completed.stdout.strip()
    return head if re.fullmatch(r"[0-9a-f]{40}", head) is not None else None


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


def core_worktree_lane_root_for(path: Path) -> Path | None:
    resolved = path.resolve(strict=False)
    parent = core_worktree_root_for(resolved)
    if parent is None:
        return None
    relative = resolved.relative_to(parent)
    if not relative.parts:
        return None
    return parent / relative.parts[0]


def validate_workspace(root: Path, *, writable: bool) -> dict[str, Any]:
    resolved = root.resolve(strict=False)
    if writable and resolved in {PRODUCTION_CORE_ROOT, CONTAINER_CORE_ROOT}:
        return decision("DENY", "GOVERNANCE_FAILURE", workspace=str(resolved))
    if not writable:
        return decision(
            "ALLOW", "GOVERNANCE_OK", workspace=str(resolved), workspace_kind="read_only"
        )
    lane_root = core_worktree_lane_root_for(resolved)
    if lane_root is None or lane_root.resolve(strict=False) != resolved:
        return decision("DENY", "GOVERNANCE_FAILURE", workspace=str(resolved))

    git_file = resolved / ".git"
    try:
        git_text = git_file.read_text(encoding="utf-8").strip()
    except OSError:
        return decision("DENY", "GOVERNANCE_FAILURE", workspace=str(resolved))
    prefix = "gitdir: "
    if not git_text.startswith(prefix):
        return decision("DENY", "GOVERNANCE_FAILURE", workspace=str(resolved))

    admin = Path(git_text[len(prefix) :].strip())
    if not admin.is_absolute():
        admin = git_file.parent / admin
    admin = admin.resolve(strict=False)
    admin_root = (PRODUCTION_CORE_ROOT / ".git" / "worktrees").resolve(strict=False)
    if not admin.is_dir() or not is_relative_to(admin, admin_root):
        return decision("DENY", "GOVERNANCE_FAILURE", workspace=str(resolved))

    try:
        backref_text = (admin / "gitdir").read_text(encoding="utf-8").strip()
    except OSError:
        return decision("DENY", "GOVERNANCE_FAILURE", workspace=str(resolved))
    backref = Path(backref_text)
    if not backref.is_absolute():
        backref = admin / backref
    if backref.resolve(strict=False) != git_file.resolve(strict=False):
        return decision("DENY", "GOVERNANCE_FAILURE", workspace=str(resolved))

    def git_output(*args: str, cwd: Path = resolved) -> str | None:
        try:
            completed = subprocess.run(
                ["git", "-C", str(cwd), *args],
                capture_output=True,
                text=True,
                check=False,
                timeout=3,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        if completed.returncode != 0:
            return None
        return completed.stdout.strip()

    top = git_output("rev-parse", "--show-toplevel")
    actual_admin = git_output("rev-parse", "--absolute-git-dir")
    common = git_output("rev-parse", "--git-common-dir")
    if not top or not actual_admin or not common:
        return decision("DENY", "GOVERNANCE_FAILURE", workspace=str(resolved))
    common_path = Path(common)
    if not common_path.is_absolute():
        common_path = resolved / common_path
    if (
        Path(top).resolve(strict=False) != resolved
        or Path(actual_admin).resolve(strict=False) != admin
        or common_path.resolve(strict=False)
        != (PRODUCTION_CORE_ROOT / ".git").resolve(strict=False)
    ):
        return decision("DENY", "GOVERNANCE_FAILURE", workspace=str(resolved))

    worktree_list = git_output("worktree", "list", "--porcelain", cwd=PRODUCTION_CORE_ROOT)
    if worktree_list is None:
        return decision("DENY", "GOVERNANCE_FAILURE", workspace=str(resolved))
    registered = {
        Path(line.removeprefix("worktree ")).resolve(strict=False)
        for line in worktree_list.splitlines()
        if line.startswith("worktree ")
    }
    if resolved not in registered:
        return decision("DENY", "GOVERNANCE_FAILURE", workspace=str(resolved))

    return decision(
        "ALLOW",
        "GOVERNANCE_OK",
        workspace=str(resolved),
        workspace_kind="isolated_worktree",
        git_admin=str(admin),
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


def validate_checkpoint_start_provenance(
    evidence_path: Path,
    payload: Any,
    *,
    artifact_root: Path,
) -> dict[str, Any]:
    """Bind checkpoint start to its durable artifact directory and manifest."""
    if not isinstance(payload, Mapping):
        return decision(
            "DENY",
            "GOVERNANCE_FAILURE",
            "CHECKPOINT_PROVENANCE_FAILURE",
            invalid=["manifest"],
        )
    checkpoint_id = payload.get("checkpoint_id")
    if not isinstance(checkpoint_id, str) or not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", checkpoint_id
    ):
        return decision(
            "DENY",
            "GOVERNANCE_FAILURE",
            "CHECKPOINT_PROVENANCE_FAILURE",
            invalid=["checkpoint_id"],
        )

    root = artifact_root.resolve(strict=False)
    directory = (root / checkpoint_id).resolve(strict=False)
    expected_start = (directory / "start.json").resolve(strict=False)
    resolved_evidence = evidence_path.resolve(strict=False)
    if resolved_evidence != expected_start:
        return decision(
            "DENY",
            "GOVERNANCE_FAILURE",
            "CHECKPOINT_PROVENANCE_FAILURE",
            expected=str(expected_start),
            actual=str(resolved_evidence),
        )
    try:
        stored_start = load_json(expected_start)
    except AdeError as error:
        return decision(
            "DENY",
            "GOVERNANCE_FAILURE",
            "CHECKPOINT_PROVENANCE_FAILURE",
            error=str(error),
        )
    if stored_start != dict(payload):
        return decision(
            "DENY",
            "GOVERNANCE_FAILURE",
            "CHECKPOINT_PROVENANCE_FAILURE",
            detail="start evidence does not match durable artifact",
        )

    work_type = payload.get("work_type")
    value_gate_sha256: str | None = None
    if work_type in VALUE_GATED_WORK_TYPES:
        value_gate_path = directory / "value-gate.json"
        try:
            durable_value_gate = load_json(value_gate_path)
        except AdeError as error:
            return decision(
                "DENY",
                "GOVERNANCE_FAILURE",
                "CHECKPOINT_PROVENANCE_FAILURE",
                error=str(error),
            )
        if payload.get("value_gate") != durable_value_gate:
            return decision(
                "DENY",
                "GOVERNANCE_FAILURE",
                "CHECKPOINT_PROVENANCE_FAILURE",
                detail="value gate does not match durable artifact",
            )
        if evaluate_checkpoint_value_gate(durable_value_gate)["status"] != "ALLOW":
            return decision(
                "DENY",
                "GOVERNANCE_FAILURE",
                "CHECKPOINT_PROVENANCE_FAILURE",
                detail="durable value gate is not allowed",
            )
        value_gate_sha256 = sha256(value_gate_path)

    return decision(
        "ALLOW",
        "CHECKPOINT_PROVENANCE_OK",
        checkpoint_id=checkpoint_id,
        artifact_dir=str(directory),
        start_sha256=sha256(expected_start),
        value_gate_sha256=value_gate_sha256,
    )


def evaluate_checkpoint_value_gate(payload: Any) -> dict[str, Any]:
    """Fail closed on unclear value or redundant custom implementation."""
    if not isinstance(payload, Mapping):
        return decision(
            "DENY",
            "GOVERNANCE_FAILURE",
            "INVALID_MANIFEST",
            invalid=["manifest"],
        )
    missing = [
        key
        for key in ("user_value", "measurement", "revenue_link", "content_proof")
        if not isinstance(payload.get(key), str) or not payload.get(key, "").strip()
    ]
    native = payload.get("native_capability")
    if not isinstance(native, Mapping):
        missing.append("native_capability")
        return decision("DENY", "GOVERNANCE_FAILURE", missing=missing)

    native_decision = native.get("decision")
    coverage = native.get("coverage_pct")
    owned_contract = native.get("owned_contract")
    rationale = native.get("rationale")
    invalid: list[str] = []
    if native_decision not in NATIVE_CAPABILITY_DECISIONS:
        invalid.append("native_capability.decision")
    if (
        isinstance(coverage, bool)
        or not isinstance(coverage, (int, float))
        or not 0 <= coverage <= 100
    ):
        invalid.append("native_capability.coverage_pct")
    if not isinstance(owned_contract, bool):
        invalid.append("native_capability.owned_contract")
    if not isinstance(rationale, str) or not rationale.strip():
        invalid.append("native_capability.rationale")
    if missing or invalid:
        return decision(
            "DENY",
            "GOVERNANCE_FAILURE",
            missing=missing,
            invalid=invalid,
        )
    if native_decision == "BUILD_CUSTOM" and coverage >= 80 and not owned_contract:
        return decision(
            "DENY",
            "GOVERNANCE_FAILURE",
            "REDUNDANT_BUILD",
            native_decision=native_decision,
            native_coverage_pct=coverage,
        )
    return decision(
        "ALLOW",
        "VALUE_GATE_OK",
        native_decision=native_decision,
        native_coverage_pct=coverage,
    )


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


def active_checkpoint(root: Path) -> dict[str, Any] | None:
    record = read_memory(root, "active-checkpoint")
    items = record.get("items")
    if not isinstance(items, list) or not items:
        return None
    latest = items[-1]
    if not isinstance(latest, dict) or latest.get("status") != "ACTIVE":
        return None
    return latest


def validate_active_checkpoint_for_mutation(root: Path) -> dict[str, Any]:
    active = active_checkpoint(root)
    if active is None:
        return decision(
            "DENY", "GOVERNANCE_FAILURE", "ACTIVE_CHECKPOINT_REQUIRED", workspace=str(root)
        )
    work_type = active.get("work_type")
    if work_type not in CHECKPOINT_WORK_TYPES:
        return decision(
            "DENY", "GOVERNANCE_FAILURE", "INVALID_CHECKPOINT_STATE", work_type=work_type
        )
    if work_type in VALUE_GATED_WORK_TYPES and active.get("value_gate_status") != "ALLOW":
        return decision(
            "DENY",
            "GOVERNANCE_FAILURE",
            "VALUE_GATE_REQUIRED",
            checkpoint_id=active.get("checkpoint_id"),
        )
    return decision(
        "ALLOW",
        "GOVERNANCE_OK",
        checkpoint_id=active.get("checkpoint_id"),
        work_type=work_type,
    )


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


def validate_closure_review_protocol(
    payload: Any, *, expected_candidate_sha: str | None
) -> dict[str, Any]:
    """Validate bounded, snapshot-bound independent closure review evidence."""
    if not isinstance(payload, Mapping):
        return decision(
            "DENY",
            "GOVERNANCE_FAILURE",
            "CLOSURE_REVIEW_PROTOCOL_REQUIRED",
        )

    if expected_candidate_sha is None or re.fullmatch(
        r"[0-9a-f]{40}", expected_candidate_sha
    ) is None:
        return decision(
            "DENY",
            "GOVERNANCE_FAILURE",
            "REVIEW_CANDIDATE_UNBOUND",
        )

    required_true = (
        "candidate_frozen",
        "adversarial_matrix_passed",
        "focused_regression_passed",
        "full_regression_passed",
        "reviewer_independent",
    )
    invalid: list[str] = []
    if payload.get("protocol_version") != CLOSURE_REVIEW_PROTOCOL_VERSION:
        invalid.append("protocol_version")

    candidate_sha = payload.get("candidate_sha")
    reviewed_sha = payload.get("reviewed_sha")
    for name, value in (("candidate_sha", candidate_sha), ("reviewed_sha", reviewed_sha)):
        if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{40}", value) is None:
            invalid.append(name)

    for name in required_true:
        if payload.get(name) is not True:
            invalid.append(name)

    rounds = payload.get("semantic_review_rounds")
    if isinstance(rounds, bool) or not isinstance(rounds, int) or rounds < 1:
        invalid.append("semantic_review_rounds")

    findings_batched = payload.get("findings_batched")
    if not isinstance(findings_batched, bool):
        invalid.append("findings_batched")

    behavior_changed = payload.get("behavior_changed_after_review")
    if not isinstance(behavior_changed, bool):
        invalid.append("behavior_changed_after_review")

    tool_failures = payload.get("tool_failures")
    if isinstance(tool_failures, bool) or not isinstance(tool_failures, int) or tool_failures < 0:
        invalid.append("tool_failures")

    if invalid:
        return decision(
            "DENY",
            "GOVERNANCE_FAILURE",
            "CLOSURE_REVIEW_PROTOCOL_INVALID",
            invalid=sorted(set(invalid)),
        )

    assert isinstance(rounds, int)
    if rounds > CLOSURE_REVIEW_MAX_SEMANTIC_ROUNDS:
        return decision(
            "DENY",
            "GOVERNANCE_FAILURE",
            "REVIEW_BUDGET_EXCEEDED",
            semantic_review_rounds=rounds,
            max_semantic_review_rounds=CLOSURE_REVIEW_MAX_SEMANTIC_ROUNDS,
        )
    if (
        candidate_sha != reviewed_sha
        or candidate_sha != expected_candidate_sha
        or behavior_changed is True
    ):
        return decision(
            "DENY",
            "GOVERNANCE_FAILURE",
            "REVIEW_CANDIDATE_STALE",
            candidate_sha=candidate_sha,
            reviewed_sha=reviewed_sha,
            expected_candidate_sha=expected_candidate_sha,
        )
    if rounds > 1 and findings_batched is not True:
        return decision(
            "DENY",
            "GOVERNANCE_FAILURE",
            "REVIEW_FINDINGS_NOT_BATCHED",
        )
    return decision(
        "ALLOW",
        "GOVERNANCE_OK",
        protocol_version=CLOSURE_REVIEW_PROTOCOL_VERSION,
        semantic_review_rounds=rounds,
        tool_failures=tool_failures,
    )


def checkpoint_gate(
    evidence: Mapping[str, Any],
    action: str,
    *,
    expected_candidate_sha: str | None = None,
) -> dict[str, Any]:
    if action == "start":
        missing: list[str] = []
        invalid: list[str] = []
        checkpoint_id = evidence.get("checkpoint_id")
        work_type = evidence.get("work_type")
        if not isinstance(checkpoint_id, str) or not checkpoint_id.strip():
            missing.append("checkpoint_id")
        if not isinstance(work_type, str) or not work_type.strip():
            missing.append("work_type")
        elif work_type not in CHECKPOINT_WORK_TYPES:
            invalid.append("work_type")

        value_result: dict[str, Any] | None = None
        if work_type in VALUE_GATED_WORK_TYPES:
            value_result = evaluate_checkpoint_value_gate(evidence.get("value_gate"))
            if value_result["status"] != "ALLOW":
                missing.append("value_gate")

        result: dict[str, Any] = {
            "status": "PASS" if not missing and not invalid else "BLOCKED",
            "missing": missing,
            "invalid": invalid,
        }
        if value_result is not None:
            result["value_gate"] = value_result
        return result

    required = ("conflict_gate", "scoped_diff", "tests", "backup", "rollback", "runtime_e2e")
    missing = [key for key in required if evidence.get(key) is not True]
    if action in {"review", "close"} and evidence.get("review") != "PASS":
        missing.insert(0, "review")
    if action in {"review", "close"}:
        protocol = validate_closure_review_protocol(
            evidence.get("closure_review"),
            expected_candidate_sha=expected_candidate_sha,
        )
        if protocol["status"] != "ALLOW":
            return {
                "status": "BLOCKED",
                "missing": missing,
                "reason": protocol["reason"],
                "code": protocol.get("code", "CLOSURE_REVIEW_PROTOCOL_INVALID"),
                "closure_review": protocol,
            }
    return {"status": "PASS" if not missing else "BLOCKED", "missing": missing}
