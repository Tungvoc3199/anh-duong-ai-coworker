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


_OBSERVATION_MARKERS = ("kiem tra", "check", "xac minh", "verify", "xem")
_STATUS_MARKERS = ("trang thai", "tinh trang", "status", "co on", "san sang")


def _has_status_language(normalized: str) -> bool:
    return any(marker in normalized for marker in _STATUS_MARKERS) or (
        "health" in normalized and "ready" in normalized
    )


def _has_observation_language(normalized: str) -> bool:
    return any(marker in normalized for marker in _OBSERVATION_MARKERS)


def _has_strong_read_only_boundary(intent: SafetyIntent) -> bool:
    explicit_components = all(
        intent.has(constraint)
        for constraint in (
            SafetyConstraint.NO_FILE_CHANGES,
            SafetyConstraint.NO_CONFIG_CHANGES,
            SafetyConstraint.NO_SERVICE_RESTART,
        )
    )
    return (
        intent.has(SafetyConstraint.READ_ONLY)
        and (intent.has(SafetyConstraint.NO_SYSTEM_MUTATION) or explicit_components)
        and not intent.unnegated_mutation
    )


def is_read_only_status_intent(intent: SafetyIntent) -> bool:
    normalized = intent.normalized_text
    return (
        _has_observation_language(normalized)
        and _has_status_language(normalized)
        and "health" in normalized
        and "ready" in normalized
        and _has_strong_read_only_boundary(intent)
    )


def is_read_only_core_status_intent(intent: SafetyIntent) -> bool:
    normalized = intent.normalized_text
    padded = f" {normalized} "
    has_core_identity = " core " in padded or " anh duong " in padded
    return (
        has_core_identity
        and _has_observation_language(normalized)
        and _has_status_language(normalized)
        and "health" in normalized
        and "ready" in normalized
        and _has_strong_read_only_boundary(intent)
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
    "changes",
    "write",
    "create",
    "delete",
)
_SIDE_EFFECT_MARKERS = _MUTATION_MARKERS + (
    "update",
    "cap nhat",
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
    "gui email",
    "send email",
    "gui slack",
    "send slack",
    "gui webhook",
    "send webhook",
    "gui zalo",
    "send zalo",
    "gui teams",
    "send teams",
    "gui messenger",
    "send messenger",
    "chay lenh",
    "run command",
    "chay script",
    "run script",
    "goi openclaw",
    "call openclaw",
    "dung model",
    "use model",
    "call model",
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

    if _contains_any(
        normalized,
        ("chi doc", "read only", "readonly", "chi xem", "view only"),
    ):
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


def _normalize_clause(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text).split())


def _starts_with_side_effect(text: str) -> bool:
    tokens = text.split()
    while tokens and tokens[0] in {"imperative", "please", "then"}:
        tokens.pop(0)
    if tokens and tokens[0] in {"neu", "if"}:
        condition_end = next(
            (
                index
                for index, token in enumerate(tokens[1:], start=1)
                if token in {"thi", "then"}
            ),
            None,
        )
        if condition_end is not None:
            tokens = tokens[condition_end + 1 :]
    residual = " ".join(tokens)
    return any(
        residual == marker or residual.startswith(f"{marker} ")
        for marker in _SIDE_EFFECT_MARKERS
    )


def _looks_like_negated_enumeration(text: str) -> bool:
    return (
        _contains_any(text, ("hoac", "or", "hay"))
        and not _contains_any(text, ("neu", "if"))
        and not text.startswith(("imperative ", "please ", "then "))
    )


def _comma_starts_new_effect_clause(text: str) -> bool:
    if not _starts_with_side_effect(text):
        return False
    return not _looks_like_negated_enumeration(text)


def _split_coordination_boundaries(clause: str) -> list[str]:
    normalized = _normalize_clause(clause)
    tokens = normalized.split()
    if not tokens:
        return []
    boundaries: list[int] = []
    for index, token in enumerate(tokens[:-1]):
        if token not in {"va", "and"}:
            continue
        tail = " ".join(tokens[index + 1 :])
        if _starts_with_side_effect(tail):
            boundaries.append(index)
    if not boundaries:
        return [clause]

    pieces: list[str] = []
    start = 0
    for boundary in boundaries:
        pieces.append(" ".join(tokens[start:boundary]))
        start = boundary + 1
    pieces.append(" ".join(tokens[start:]))
    return [piece for piece in pieces if piece]


def _semantic_clauses(text: str) -> list[str]:
    folded = _fold_preserving_boundaries(text)
    primary = re.split(
        r"[.!?;\n]+|\b(?:nhung|but|however|then)\b",
        folded,
    )
    clauses: list[str] = []
    for raw_clause in primary:
        combined = ""
        for fragment in raw_clause.split(","):
            normalized_fragment = _normalize_clause(fragment)
            if combined and _comma_starts_new_effect_clause(normalized_fragment):
                clauses.extend(_split_coordination_boundaries(combined))
                combined = fragment
            else:
                combined = f"{combined} {fragment}".strip()
        if combined:
            clauses.extend(_split_coordination_boundaries(combined))
    return clauses


def _negated_scopes(text: str) -> list[str]:
    scopes: list[str] = []
    for clause in _semantic_clauses(text):
        normalized_clause = _normalize_clause(clause)
        tokens = normalized_clause.split()
        for index, token in enumerate(tokens):
            if token not in {"khong", "no"}:
                continue
            end = len(tokens)
            for cursor in range(index + 1, len(tokens)):
                if tokens[cursor] in _CONTRAST_TOKENS or tokens[cursor] in {"khong", "no"}:
                    end = cursor
                    break
            scopes.append(" ".join(tokens[index:end]))
    return scopes


def _has_unnegated_mutation(text: str) -> bool:
    for clause in _semantic_clauses(text):
        normalized_clause = _normalize_clause(clause)
        if not _contains_any(normalized_clause, _SIDE_EFFECT_MARKERS):
            continue
        residual = f" {normalized_clause} "
        for scope in _negated_scopes(clause):
            residual = residual.replace(f" {scope} ", " ")
        if _contains_any(" ".join(residual.split()), _SIDE_EFFECT_MARKERS):
            return True
    return False


def _fold_preserving_boundaries(text: str) -> str:
    lowered = text.casefold()
    lowered = lowered.replace("đừng", "không")
    lowered = lowered.replace("hãy", "imperative")
    lowered = lowered.replace("rồi", "then")
    lowered = re.sub(r"don['’]t", "no", lowered)
    lowered = re.sub(r"\bdo not\b", "no", lowered)
    decomposed = unicodedata.normalize("NFKD", lowered)
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
    if _contains_any(scope, ("no changes", "khong thay doi gi", "khong sua gi")):
        return True
    has_broad_quantifier = _contains_any(
        scope,
        ("gi", "anything", "any change", "any changes"),
    )
    if has_broad_quantifier and _contains_any(scope, _SIDE_EFFECT_MARKERS):
        return True
    has_system = _contains_any(scope, ("he thong", "system"))
    return has_system and _contains_any(scope, _SIDE_EFFECT_MARKERS)
