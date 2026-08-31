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


_OBSERVATION_MARKERS = (
    "kiem tra",
    "check",
    "xac minh",
    "verify",
    "xem",
    "doc",
    "read",
    "inspect",
    "liet ke",
    "list",
)
_STATUS_MARKERS = ("trang thai", "tinh trang", "status", "co on", "san sang")
_READ_ONLY_MARKERS = ("chi doc", "read only", "readonly", "chi xem", "view only")
_REPORT_PREFIX_MARKERS = (
    "gui ket qua",
    "bang chung",
    "evidence",
    "send result",
    "send results",
    "tra loi",
    "answer",
    "return result",
    "return results",
    "provide the result",
    "provide the results",
    "show me the result",
    "show me the results",
    "report",
    "tell me",
    "bao ngan gon",
    "bao ket qua",
    "bao lai ket qua",
    "tra ve ket qua",
    "bao thanh cong",
    "bao anh",
    "bao cao",
    "summary",
    "tom tat",
    "giai thich",
    "explain",
    "ket luan",
    "conclusion",
    "yeu cau",
    "requirement",
    "requirements",
    "chi bao thanh cong",
)
_SAFE_SCAFFOLD_PREFIXES = (
    "thuc hien mot workflow",
    "workflow",
    "soan checklist",
    "draft checklist",
)
_SAFE_CONTINUATION_CLAUSES = frozenset(
    {
        "health",
        "ready",
        "status",
        "core",
        "core service",
        "database",
        "database quick check",
        "db",
        "db quick check",
        "pragma",
        "pragma quick check",
        "quick check",
        "file",
        "tep",
        "config",
        "cau hinh",
        "service",
        "git",
        "model",
        "openclaw",
        "he thong",
        "system",
        "duong",
        "thoi",
    }
)


_SAFE_STATUS_OBSERVATION_TOKENS = frozenset(
    {
        "actual",
        "anh",
        "bang",
        "che",
        "check",
        "co",
        "core",
        "cua",
        "database",
        "db",
        "do",
        "duong",
        "giup",
        "gateway",
        "health",
        "he",
        "hien",
        "is",
        "me",
        "now",
        "of",
        "ok",
        "on",
        "pragma",
        "quick",
        "ready",
        "san",
        "service",
        "status",
        "system",
        "tai",
        "the",
        "them",
        "thong",
        "thuc",
        "tinh",
        "trang",
        "te",
        "tu",
        "va",
        "and",
        "whether",
        "current",
        "thai",
        "xem",
        "only",
        "read",
        "readonly",
        "chi",
        "doc",
        "thoi",
        "kiem",
        "tra",
        "xac",
        "minh",
        "please",
        "cho",
        "dang",
        "hay",
        "khong",
        "slash",
        "file",
        "tep",
        "readme",
        "md",
        "du",
        "an",
        "project",
        "inspect",
        "list",
        "liet",
        "ke",
        "verify",
    }
)
_SAFE_NEGATION_TOKENS = frozenset(
    {
        "and",
        "anything",
        "any",
        "cai",
        "cau",
        "changes",
        "change",
        "chay",
        "chi",
        "command",
        "commands",
        "config",
        "dat",
        "deploy",
        "dich",
        "doi",
        "dong",
        "effect",
        "file",
        "git",
        "gi",
        "goi",
        "hay",
        "he",
        "hinh",
        "hoac",
        "install",
        "khai",
        "khong",
        "khoi",
        "lai",
        "lenh",
        "model",
        "mo",
        "no",
        "openclaw",
        "or",
        "package",
        "restart",
        "service",
        "side",
        "sua",
        "system",
        "tep",
        "thay",
        "thong",
        "thuc",
        "hien",
        "trien",
        "use",
        "vu",
        "write",
        "run",
        "script",
        "invocation",
        "mutation",
        "modify",
        "edit",
        "create",
        "delete",
        "update",
        "push",
        "merge",
        "commit",
        "publish",
        "upload",
        "email",
        "slack",
        "webhook",
        "zalo",
        "teams",
        "messenger",
        "nothing",
        "none",
    }
)

_SAFE_REPORT_TOKENS = frozenset(
    {
        "actual",
        "anh",
        "answer",
        "bang",
        "bao",
        "briefly",
        "cao",
        "cho",
        "co",
        "conclusion",
        "database",
        "evidence",
        "explain",
        "giai",
        "gui",
        "health",
        "he",
        "is",
        "ket",
        "khong",
        "luan",
        "me",
        "ngan",
        "only",
        "provide",
        "qua",
        "quick",
        "ready",
        "real",
        "report",
        "result",
        "results",
        "return",
        "san",
        "send",
        "show",
        "summary",
        "system",
        "tell",
        "thanh",
        "that",
        "thich",
        "thong",
        "thuc",
        "to",
        "tom",
        "tra",
        "ve",
        "when",
        "whether",
        "dang",
        "hay",
        "if",
        "the",
        "a",
        "lai",
        "success",
        "check",
        "kiem",
        "cong",
        "khi",
        "chung",
        "gon",
        "yeu",
        "cau",
        "sang",
    }
)
_SAFE_SCAFFOLD_TOKENS = _SAFE_STATUS_OBSERVATION_TOKENS | frozenset(
    {"mot", "workflow", "soan", "checklist", "draft", "buoc"}
)
_SAFE_REPORT_EXACT_PREFIXES = (
    "ket luan co the tiep tuc lam viec hay khong",
    "conclusion whether can continue working",
)
_SAFE_IDENTIFIER_PREFIXES = ("wr", "tg", "dr", "ad", "risk", "run", "task", "session", "request")


def _has_status_language(normalized: str) -> bool:
    return any(marker in normalized for marker in _STATUS_MARKERS) or (
        "health" in normalized and "ready" in normalized
    )


def _has_observation_language(normalized: str) -> bool:
    observation_text = normalized
    for marker in _READ_ONLY_MARKERS:
        observation_text = observation_text.replace(marker, " ")
    observation_text = " ".join(observation_text.split())
    return _contains_any(observation_text, _OBSERVATION_MARKERS)


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
    has_core_identity = (
        " anh duong " in padded
        or " core service " in padded
        or " core tu kiem tra " in padded
        or " core check " in padded
    )
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
    return "quick check" in normalized and _contains_any(
        normalized,
        ("database", "db", "pragma"),
    )


_CONTRAST_TOKENS = frozenset(
    {"nhung", "but", "however", "except", "excluding", "ngoai", "tru", "unless"}
)
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
    "start service",
    "stop service",
    "enable service",
    "disable service",
    "reload service",
    "khoi dong service",
    "dung service",
    "bat service",
    "tat service",
    "reboot",
    "shutdown",
    "kill process",
    "terminate process",
    "systemctl",
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


def _has_unnegated_read_only_marker(text: str) -> bool:
    for clause in _semantic_clauses(text):
        tokens = _normalize_clause(clause).split()
        for marker in _READ_ONLY_MARKERS:
            marker_tokens = marker.split()
            width = len(marker_tokens)
            for index in range(0, len(tokens) - width + 1):
                if tokens[index : index + width] != marker_tokens:
                    continue
                previous = tokens[max(0, index - 2) : index]
                if previous[-1:] and previous[-1] in {"khong", "no", "not"}:
                    continue
                if previous[-2:] in (["khong", "phai"], ["do", "not"]):
                    continue
                return True
    return False


def analyze_safety_intent(text: str) -> SafetyIntent:
    normalized = normalize_semantic_text(text)
    scopes = tuple(_negated_scopes(text))
    detected: list[SafetyConstraint] = []

    if _has_unnegated_read_only_marker(text):
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
            (index for index, token in enumerate(tokens[1:], start=1) if token in {"thi", "then"}),
            None,
        )
        if condition_end is not None:
            tokens = tokens[condition_end + 1 :]
        else:
            effect_start = next(
                (
                    index
                    for index in range(1, len(tokens))
                    if _starts_with_side_effect(" ".join(tokens[index:]))
                ),
                None,
            )
            if effect_start is not None:
                tokens = tokens[effect_start:]
    residual = " ".join(tokens)
    return any(
        residual == marker or residual.startswith(f"{marker} ") for marker in _SIDE_EFFECT_MARKERS
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



def _preserve_shared_negation_target_slashes(text: str) -> str:
    return re.sub(
        r"\b(file|config|tep|cau hinh)\s*/\s*(file|config|tep|cau hinh)\b",
        r"\1 \2",
        text,
    )

def _semantic_clauses(text: str) -> list[str]:
    folded = _preserve_shared_negation_target_slashes(_fold_preserving_boundaries(text))
    primary = re.split(
        r"[.!?;\n]+|\b(?:nhung|but|however|then|except|excluding|ngoai\s+tru|tru\s+khi|unless|before|after|while|truoc\s+khi|sau\s+khi|trong\s+khi)\b",
        folded,
    )
    clauses: list[str] = []
    for raw_clause in primary:
        combined = ""
        for fragment in re.split(r"[,/:\u2013\u2014]+|->|=>", raw_clause):
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
                if tokens[cursor] in {"neu", "if"} and _starts_with_side_effect(
                    " ".join(tokens[cursor:])
                ):
                    end = cursor
                    break
            scopes.append(" ".join(tokens[index:end]))
    return scopes


def _strip_clause_prefixes(normalized_clause: str) -> str:
    tokens = normalized_clause.split()
    while tokens and tokens[0] in {"please", "imperative", "chi", "only"}:
        tokens.pop(0)
    return " ".join(tokens)


def _starts_with_any(normalized_clause: str, markers: tuple[str, ...]) -> bool:
    return any(
        normalized_clause == marker or normalized_clause.startswith(f"{marker} ")
        for marker in markers
    )


def _looks_like_identifier_clause(normalized_clause: str) -> bool:
    tokens = normalized_clause.split()
    if not tokens or not all(any(character.isdigit() for character in token) for token in tokens):
        return False
    return any(tokens[0].startswith(prefix) for prefix in _SAFE_IDENTIFIER_PREFIXES)


def _is_harmless_readonly_clause(
    normalized_clause: str,
    *,
    strict_status: bool = False,
) -> bool:
    if not normalized_clause:
        return True
    tokens = normalized_clause.split()
    if normalized_clause in {
        "make no change",
        "make no changes",
        "no make change",
        "no make changes",
        "no make any change",
        "no make any changes",
    }:
        return True
    if tokens and tokens[0] in {"khong", "no"}:
        return all(token in _SAFE_NEGATION_TOKENS for token in tokens)
    if normalized_clause in _SAFE_CONTINUATION_CLAUSES:
        return True
    if _looks_like_identifier_clause(normalized_clause):
        return True

    stripped = _strip_clause_prefixes(normalized_clause)
    if _starts_with_any(stripped, _OBSERVATION_MARKERS):
        return all(token in _SAFE_STATUS_OBSERVATION_TOKENS for token in stripped.split())
    if _starts_with_any(stripped, _SAFE_SCAFFOLD_PREFIXES):
        if strict_status:
            return all(
                token in _SAFE_SCAFFOLD_TOKENS or any(character.isdigit() for character in token)
                for token in stripped.split()
            )
        return True
    if _starts_with_any(stripped, _REPORT_PREFIX_MARKERS):
        if strict_status:
            if stripped in _SAFE_REPORT_EXACT_PREFIXES:
                return True
            return all(token in _SAFE_REPORT_TOKENS for token in stripped.split())
        return True
    stripped_tokens = stripped.split()
    if stripped_tokens and stripped_tokens[0] in {"health", "ready"}:
        return all(token in _SAFE_STATUS_OBSERVATION_TOKENS for token in stripped_tokens)
    if stripped_tokens and stripped_tokens[0] == "core" and _has_observation_language(stripped):
        return all(token in _SAFE_STATUS_OBSERVATION_TOKENS for token in stripped_tokens)
    if stripped_tokens and stripped_tokens[0] in {"neu", "if"}:
        for boundary in ("thi", "then"):
            if boundary in stripped_tokens:
                tail = _strip_clause_prefixes(
                    " ".join(stripped_tokens[stripped_tokens.index(boundary) + 1 :])
                )
                if not _starts_with_any(tail, _REPORT_PREFIX_MARKERS):
                    return False
                if strict_status:
                    if tail in _SAFE_REPORT_EXACT_PREFIXES:
                        return True
                    return all(token in _SAFE_REPORT_TOKENS for token in tail.split())
                return True
    return False


def _sequence_clauses(text: str) -> list[str]:
    folded = _preserve_shared_negation_target_slashes(_fold_preserving_boundaries(text))
    folded = re.sub(r"(?<=[a-z0-9])\.(?=[a-z0-9])", " ", folded)
    primary = re.split(
        r"[.!?;:/\n\u2013\u2014]+|->|=>|\b(?:nhung|but|however|then|except|excluding|ngoai\s+tru|tru\s+khi|unless|before|after|while|truoc\s+khi|sau\s+khi|trong\s+khi|va|and)\b",
        folded,
    )
    clauses: list[str] = []
    for primary_clause in primary:
        fragments = [
            normalized
            for raw in primary_clause.split(",")
            if (normalized := _normalize_clause(raw))
        ]
        index = 0
        while index < len(fragments):
            current = fragments[index]
            if (
                current.split()[:1] in [["khong"], ["no"]]
                and index + 1 < len(fragments)
                and _contains_any(fragments[index + 1], ("hoac", "or", "hay"))
                and not _contains_any(fragments[index + 1], ("neu", "if"))
            ):
                clauses.append(f"{current} {fragments[index + 1]}")
                index += 2
                continue
            clauses.append(current)
            index += 1
    return clauses


def _has_ambiguous_readonly_action(text: str) -> bool:
    if not _has_unnegated_read_only_marker(text):
        return False
    normalized = normalize_semantic_text(text)
    strict_status = (
        _has_status_language(normalized) and "health" in normalized and "ready" in normalized
    )
    clauses = _sequence_clauses(text)
    for clause in clauses:
        matching_marker = next(
            (marker for marker in _READ_ONLY_MARKERS if _contains_any(clause, (marker,))),
            None,
        )
        if matching_marker is not None:
            prefix, suffix = clause.split(matching_marker, 1)
            prefix = prefix.strip()
            suffix = suffix.strip()
            if prefix and not _is_harmless_readonly_clause(prefix, strict_status=strict_status):
                return True
            if suffix and not _is_harmless_readonly_clause(suffix, strict_status=strict_status):
                return True
            continue
        if not _is_harmless_readonly_clause(clause, strict_status=strict_status):
            return True
    return False


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
    return _has_ambiguous_readonly_action(text)


def _fold_preserving_boundaries(text: str) -> str:
    lowered = text.casefold()
    lowered = lowered.replace("đừng", "không")
    lowered = lowered.replace("hãy", "imperative")
    lowered = lowered.replace("rồi", "then")
    lowered = re.sub(r"don['’]t", "no", lowered)
    lowered = re.sub(r"\bdo not\b", "no", lowered)
    decomposed = unicodedata.normalize("NFKD", lowered)
    folded = "".join(
        character for character in decomposed if not unicodedata.combining(character)
    ).replace("đ", "d")
    folded = re.sub(r"\bsau\s+(?:do|day)\b", " then ", folded)
    folded = re.sub(r"\btiep\s+theo\b", " then ", folded)
    return folded


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
    if _contains_any(
        scope,
        (
            "no changes",
            "no make change",
            "no make changes",
            "no make any change",
            "no make any changes",
            "make no change",
            "make no changes",
            "khong thay doi gi",
            "khong sua gi",
        ),
    ):
        return True
    has_broad_quantifier = _contains_any(
        scope,
        ("gi", "anything", "any change", "any changes"),
    )
    if has_broad_quantifier and _contains_any(scope, _SIDE_EFFECT_MARKERS):
        return True
    has_system = _contains_any(scope, ("he thong", "system"))
    return has_system and _contains_any(scope, _SIDE_EFFECT_MARKERS)
