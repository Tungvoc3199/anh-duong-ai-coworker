from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from enum import StrEnum


class SafetyConstraint(StrEnum):
    READ_ONLY = "read_only"
    NO_COMMANDS = "no_commands"
    NO_FILE_CHANGES = "no_file_changes"
    NO_CONFIG_CHANGES = "no_config_changes"
    NO_SERVICE_RESTART = "no_service_restart"
    NO_GIT = "no_git"
    NO_OPENCLAW = "no_openclaw"
    NO_MODEL = "no_model"
    NO_PACKAGE_INSTALL = "no_package_install"
    NO_DEPLOY = "no_deploy"
    NO_SYSTEM_MUTATION = "no_system_mutation"


@dataclass(frozen=True, slots=True)
class SafetyIntent:
    normalized_text: str
    constraints: tuple[SafetyConstraint, ...]
    unnegated_mutation: bool

    def has(self, constraint: SafetyConstraint) -> bool:
        return constraint in self.constraints

    def values(self) -> tuple[str, ...]:
        return tuple(item.value for item in self.constraints)


def _has_status_language(normalized: str) -> bool:
    return any(marker in normalized for marker in ("trang thai", "tinh trang", "status"))


def is_read_only_status_intent(intent: SafetyIntent) -> bool:
    normalized = intent.normalized_text
    return (
        "kiem tra" in normalized
        and _has_status_language(normalized)
        and "health" in normalized
        and "ready" in normalized
        and intent.has(SafetyConstraint.READ_ONLY)
        and intent.has(SafetyConstraint.NO_FILE_CHANGES)
        and intent.has(SafetyConstraint.NO_CONFIG_CHANGES)
        and intent.has(SafetyConstraint.NO_SERVICE_RESTART)
        and not intent.unnegated_mutation
    )


def is_read_only_core_status_intent(intent: SafetyIntent) -> bool:
    normalized = intent.normalized_text
    padded = f" {normalized} "
    has_core_identity = " core " in padded or " anh duong " in padded
    return (
        has_core_identity
        and "kiem tra" in normalized
        and _has_status_language(normalized)
        and "health" in normalized
        and "ready" in normalized
        and intent.has(SafetyConstraint.READ_ONLY)
        and intent.has(SafetyConstraint.NO_SERVICE_RESTART)
        and not intent.unnegated_mutation
    )


def requests_database_quick_check(intent: SafetyIntent) -> bool:
    normalized = intent.normalized_text
    return "database" in normalized and "quick check" in normalized


_CONTRAST_TOKENS = frozenset({"nhung", "but", "however"})
_MUTATION_MARKERS = (
    "sua",
    "chinh sua",
    "thay doi",
    "doi",
    "ghi",
    "tao",
    "xoa",
    "edit",
    "modify",
    "change",
    "write",
    "create",
    "delete",
)
_SIDE_EFFECT_MARKERS = _MUTATION_MARKERS + (
    "restart",
    "khoi dong lai",
    "deploy",
    "trien khai",
    "install",
    "cai dat",
    "uninstall",
    "go cai dat",
    "push",
    "merge",
    "commit",
    "publish",
    "upload",
    "send",
    "gui",
)
_INVOKE_MARKERS = (
    "goi",
    "dung",
    "su dung",
    "chay",
    "call",
    "use",
    "invoke",
    "run",
)


def normalize_semantic_text(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    without_marks = "".join(
        character for character in decomposed if not unicodedata.combining(character)
    ).replace("đ", "d")
    return " ".join(re.sub(r"[^a-z0-9]+", " ", without_marks).split())


def analyze_safety_intent(text: str) -> SafetyIntent:
    normalized = normalize_semantic_text(text)
    scopes = tuple(_negated_scopes(text))
    detected: list[SafetyConstraint] = []

    if _contains_any(normalized, ("chi doc", "read only", "readonly")):
        detected.append(SafetyConstraint.READ_ONLY)
    if any(_is_no_commands(scope) for scope in scopes):
        detected.append(SafetyConstraint.NO_COMMANDS)
    if any(_is_no_file_change(scope) for scope in scopes):
        detected.append(SafetyConstraint.NO_FILE_CHANGES)
    if any(_is_no_config_change(scope) for scope in scopes):
        detected.append(SafetyConstraint.NO_CONFIG_CHANGES)
    if any(_contains_any(scope, ("restart", "khoi dong lai")) for scope in scopes):
        detected.append(SafetyConstraint.NO_SERVICE_RESTART)
    if any(_is_no_git(scope) for scope in scopes):
        detected.append(SafetyConstraint.NO_GIT)
    if any(_is_no_invocation(scope, ("openclaw",)) for scope in scopes):
        detected.append(SafetyConstraint.NO_OPENCLAW)
    if any(_is_no_invocation(scope, ("model", "mo hinh")) for scope in scopes):
        detected.append(SafetyConstraint.NO_MODEL)
    if any(_contains_any(scope, ("install", "cai dat")) for scope in scopes):
        detected.append(SafetyConstraint.NO_PACKAGE_INSTALL)
    if any(_contains_any(scope, ("deploy", "trien khai")) for scope in scopes):
        detected.append(SafetyConstraint.NO_DEPLOY)
    if any(_is_no_system_mutation(scope) for scope in scopes):
        detected.append(SafetyConstraint.NO_SYSTEM_MUTATION)

    return SafetyIntent(
        normalized_text=normalized,
        constraints=tuple(dict.fromkeys(detected)),
        unnegated_mutation=_has_unnegated_mutation(text),
    )


def _negated_scopes(text: str) -> list[str]:
    folded = _fold_preserving_boundaries(text)
    scopes: list[str] = []
    for clause in re.split(r"[.!?;\n]+", folded):
        normalized_clause = " ".join(re.sub(r"[^a-z0-9]+", " ", clause).split())
        tokens = normalized_clause.split()
        for index, token in enumerate(tokens):
            if token not in {"khong", "no"}:
                continue
            end = len(tokens)
            for cursor in range(index + 1, len(tokens)):
                if tokens[cursor] in _CONTRAST_TOKENS:
                    end = cursor
                    break
            scopes.append(" ".join(tokens[index:end]))
    return scopes


def _starts_with_positive_command(text: str) -> bool:
    tokens = text.split()
    if not tokens or tokens[0] not in {"hay", "please", "then", "roi"}:
        return False
    tokens.pop(0)
    residual = " ".join(tokens)
    return any(
        residual == marker or residual.startswith(f"{marker} ") for marker in _SIDE_EFFECT_MARKERS
    )


def _side_effect_clauses(text: str) -> list[str]:
    folded = _fold_preserving_boundaries(text)
    primary = re.split(
        r"[.!?;\n]+|\b(?:nhung|but|however)\b",
        folded,
    )
    clauses: list[str] = []
    for raw_clause in primary:
        combined = ""
        for fragment in raw_clause.split(","):
            normalized_fragment = " ".join(re.sub(r"[^a-z0-9]+", " ", fragment).split())
            if combined and _starts_with_positive_command(normalized_fragment):
                clauses.append(combined)
                combined = fragment
            else:
                combined = f"{combined} {fragment}".strip()
        if combined:
            clauses.append(combined)
    return clauses


def _has_unnegated_mutation(text: str) -> bool:
    for clause in _side_effect_clauses(text):
        normalized_clause = " ".join(re.sub(r"[^a-z0-9]+", " ", clause).split())
        residual = f" {normalized_clause} "
        for scope in _negated_scopes(clause):
            residual = residual.replace(f" {scope} ", " ")
        if _contains_any(
            " ".join(residual.split()),
            _SIDE_EFFECT_MARKERS,
        ):
            return True
    return False


def _fold_preserving_boundaries(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(
        character for character in decomposed if not unicodedata.combining(character)
    ).replace("đ", "d")


def _contains_any(text: str, phrases: tuple[str, ...]) -> bool:
    padded = f" {text} "
    return any(f" {phrase} " in padded for phrase in phrases)


def _is_no_commands(scope: str) -> bool:
    return _contains_any(
        scope,
        ("chay lenh", "run command", "run commands", "no commands"),
    )


def _is_no_file_change(scope: str) -> bool:
    return _contains_any(scope, ("file", "tep")) and _contains_any(
        scope,
        _MUTATION_MARKERS,
    )


def _is_no_config_change(scope: str) -> bool:
    return _contains_any(scope, ("config", "cau hinh")) and _contains_any(
        scope,
        _MUTATION_MARKERS,
    )


def _is_no_git(scope: str) -> bool:
    if not _contains_any(scope, ("git",)):
        return False
    return _contains_any(scope, _INVOKE_MARKERS) or scope in {"khong git", "no git"}


def _is_no_invocation(scope: str, targets: tuple[str, ...]) -> bool:
    if not _contains_any(scope, targets):
        return False
    return _contains_any(scope, _INVOKE_MARKERS) or any(
        scope == f"khong {target}" or scope == f"no {target}" for target in targets
    )


def _is_no_system_mutation(scope: str) -> bool:
    if _contains_any(scope, ("side effect", "system mutation")):
        return True
    has_system = _contains_any(scope, ("he thong", "system"))
    return has_system and _contains_any(scope, _MUTATION_MARKERS)
