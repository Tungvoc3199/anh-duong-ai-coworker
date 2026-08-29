from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable

from app.routing.models import FastRoute, RouteDecision

_WORKFLOW_PHRASES = (
    "lap ke hoach",
    "tao",
    "sua",
    "cap nhat",
    "ghi file",
    "chay",
    "thuc hien",
    "trien khai",
    "xay",
    "khac phuc",
    "xoa",
    "gui",
    "cai dat",
    "khoi dong lai",
    "doi ten",
    "di chuyen",
    "sao chep",
    "luu thong tin",
    "ghi nho rang",
    "plan",
    "create",
    "edit",
    "update",
    "write",
    "run",
    "execute",
    "implement",
    "build",
    "fix",
    "delete",
    "remove",
    "send",
    "deploy",
    "install",
    "commit",
    "push",
    "restart",
    "change",
    "modify",
    "generate",
    "move",
    "copy",
    "publish",
    "list files",
    "break down",
    "call",
    "save this",
    "store this",
    "remember this",
)
_WORKFLOW_DIRECTIVE_PHRASES = (
    "soan checklist",
)
_SEQUENTIAL_EXECUTION_MARKERS = (
    "roi",
    "sau do",
    "then",
)

_MEMORY_INHERENT_PHRASES = (
    "nho lai",
    "ban co nho",
    "toi da noi gi",
    "do you remember",
    "what did i say",
    "what have i saved",
    "recall",
)
_MEMORY_STORAGE_PHRASES = (
    "bo nho",
    "memory",
    "da luu",
    "stored",
    "saved",
)
_MEMORY_READ_PHRASES = (
    "tim",
    "tra cuu",
    "truy xuat",
    "xem lai",
    "cho toi biet",
    "search",
    "find",
    "retrieve",
    "look up",
)

_CORE_ENTITY_PHRASES = (
    "project",
    "du an",
    "task",
    "nhiem vu",
    "core",
    "anh duong",
)
_CORE_STATUS_PHRASES = (
    "trang thai",
    "tien do",
    "the nao",
    "health",
    "ready",
    "status",
    "progress",
    "how is",
    "current state",
    "hoat dong",
    "on khong",
)
_CORE_READ_PHRASES = (
    "xem",
    "kiem tra",
    "hien thi",
    "show",
    "view",
    "list",
    "get",
)

_FOLLOW_UP_UTTERANCES = frozenset(
    {
        "xong chua",
        "sao roi",
        "on chua",
        "the nao roi",
    }
)
_QUESTION_ONLY_PATTERN = re.compile(r"^\s*[?？]+\s*$")

_DIRECT_UTTERANCES = frozenset(
    {
        "ok",
        "okay",
        "duoc",
        "da",
        "da ro",
        "vang",
        "dong y",
        "dung",
        "dung roi",
        "toi hieu",
        "toi hieu roi",
        "vang toi hieu roi",
        "tot",
        "tot lam",
        "tuyet",
        "tuyet voi",
        "great",
        "got it",
        "nice",
        "sounds good",
        "chao ban khoe khong",
        "how are you",
    }
)
_ADVISORY_PHRASES = (
    "chi dan",
    "huong dan",
    "cach",
    "the nao",
    "nhu nao",
    "nen",
    "tai sao",
    "cho anh lenh",
    "cho toi lenh",
    "noi anh cach",
    "noi toi cach",
    "cho anh biet cach",
    "cho toi biet cach",
    "em nghi",
    "tu chay",
    "anh tu chay",
    "toi tu chay",
    "how to",
    "instructions",
    "guide me",
    "tell me how",
    "what should",
    "why",
    "advice",
)
_OPERATIONAL_ENTITY_PHRASES = (
    "openclaw",
    "docker",
    "docker compose",
    "wsl",
    "systemd",
    "9router",
    "gateway",
)
_OPERATIONAL_QUERY_PHRASES = (
    "o dau",
    "dang chay",
    "duong dan",
    "path",
    "where",
    "which command",
    "what command",
)
_GREETING_PATTERN = re.compile(
    r"^(?:xin chao|chao|chao buoi sang|hello|hi|hey|good morning|"
    r"good afternoon|good evening)"
    r"(?: (?:ban|anh duong|there))?$"
)
_THANKS_PATTERN = re.compile(
    r"^(?:cam on|thank you|thanks)(?: (?:ban|anh duong|nhe|rat nhieu|so much))?$"
)
_SIMPLE_ARITHMETIC_PATTERN = re.compile(
    r"^(?:tg1 direct [0-9]+ )?tinh [0-9]+(?: [0-9]+)+ va tra loi ngan gon$"
)


class FastRouter:
    """Deterministic domain router with fail-closed workflow fallback."""

    def route(self, request: str) -> RouteDecision:
        normalized = self._normalize(request)
        if not normalized:
            if _QUESTION_ONLY_PATTERN.fullmatch(request) is not None:
                return RouteDecision(
                    route=FastRoute.DIRECT,
                    rule_id="routing.direct.follow_up",
                    reason="A punctuation-only follow-up has no new execution objective.",
                )
            return RouteDecision(
                route=FastRoute.WORKFLOW,
                rule_id="routing.workflow.empty_input",
                reason="Empty input is routed to workflow for safe handling.",
            )

        if normalized in _FOLLOW_UP_UTTERANCES:
            return RouteDecision(
                route=FastRoute.DIRECT,
                rule_id="routing.direct.follow_up",
                reason="The message is a conversational follow-up without a new objective.",
            )

        if self._contains_any(normalized, _WORKFLOW_DIRECTIVE_PHRASES):
            return RouteDecision(
                route=FastRoute.WORKFLOW,
                rule_id="routing.workflow.explicit_action",
                reason="An explicit action or side effect requires workflow handling.",
            )

        advisory_request = self._is_advisory_request(normalized)
        if self._is_operational_guidance_request(
            normalized,
            advisory_request,
        ):
            return RouteDecision(
                route=FastRoute.WORKFLOW,
                rule_id="routing.workflow.operational_guidance",
                reason=(
                    "Operational guidance requires runtime-verified workflow "
                    "handling."
                ),
            )
        if (
            self._contains_any(normalized, _WORKFLOW_PHRASES)
            and (
                not advisory_request
                or self._has_sequential_execution_intent(normalized)
            )
        ):
            return RouteDecision(
                route=FastRoute.WORKFLOW,
                rule_id="routing.workflow.explicit_action",
                reason="An explicit action or side effect requires workflow handling.",
            )

        if self._is_memory_request(normalized):
            return RouteDecision(
                route=FastRoute.MEMORY,
                rule_id="routing.memory.explicit_retrieval",
                reason="The request explicitly asks to retrieve stored information.",
            )

        if self._is_core_read_request(normalized):
            return RouteDecision(
                route=FastRoute.CORE_READ,
                rule_id="routing.core_read.status_query",
                reason="The request asks for read-only Core, Project, or Task status.",
            )

        if advisory_request:
            return RouteDecision(
                route=FastRoute.DIRECT,
                rule_id="routing.direct.advisory_action_mention",
                reason=(
                    "The request asks for guidance or explanation rather than "
                    "bot-executed side effects."
                ),
            )

        if self._is_direct_request(normalized):
            return RouteDecision(
                route=FastRoute.DIRECT,
                rule_id="routing.direct.simple_conversation",
                reason="The request is a simple conversational response.",
            )

        return RouteDecision(
            route=FastRoute.DIRECT,
            rule_id="routing.direct.no_explicit_execution_intent",
            reason="No explicit execution intent was detected; use direct conversation.",
        )

    @classmethod
    def _is_memory_request(cls, normalized: str) -> bool:
        if cls._contains_any(normalized, _MEMORY_INHERENT_PHRASES):
            return True
        return cls._contains_any(
            normalized,
            _MEMORY_STORAGE_PHRASES,
        ) and cls._contains_any(normalized, _MEMORY_READ_PHRASES)

    @classmethod
    def _is_core_read_request(cls, normalized: str) -> bool:
        if not cls._contains_any(normalized, _CORE_ENTITY_PHRASES):
            return False
        return cls._contains_any(
            normalized,
            _CORE_STATUS_PHRASES,
        ) or cls._contains_any(normalized, _CORE_READ_PHRASES)

    @classmethod
    def _is_advisory_request(cls, normalized: str) -> bool:
        return cls._contains_any(normalized, _ADVISORY_PHRASES)

    @classmethod
    def _is_operational_guidance_request(
        cls,
        normalized: str,
        advisory_request: bool,
    ) -> bool:
        if not cls._contains_any(normalized, _OPERATIONAL_ENTITY_PHRASES):
            return False
        return advisory_request or cls._contains_any(
            normalized,
            _OPERATIONAL_QUERY_PHRASES,
        )

    @classmethod
    def _has_sequential_execution_intent(cls, normalized: str) -> bool:
        for marker in _SEQUENTIAL_EXECUTION_MARKERS:
            segments = normalized.split(f" {marker} ")
            if len(segments) < 2:
                continue
            if any(cls._contains_any(segment, _WORKFLOW_PHRASES) for segment in segments[1:]):
                return True
        return False

    @staticmethod
    def _is_direct_request(normalized: str) -> bool:
        return (
            normalized in _DIRECT_UTTERANCES
            or _GREETING_PATTERN.fullmatch(normalized) is not None
            or _THANKS_PATTERN.fullmatch(normalized) is not None
            or _SIMPLE_ARITHMETIC_PATTERN.fullmatch(normalized) is not None
        )

    @staticmethod
    def _contains_any(normalized: str, phrases: Iterable[str]) -> bool:
        padded = f" {normalized} "
        return any(f" {phrase} " in padded for phrase in phrases)

    @staticmethod
    def _normalize(request: str) -> str:
        decomposed = unicodedata.normalize("NFKD", request.casefold())
        without_marks = "".join(
            character
            for character in decomposed
            if not unicodedata.combining(character)
        ).replace("đ", "d")
        return " ".join(re.sub(r"[^a-z0-9]+", " ", without_marks).split())
