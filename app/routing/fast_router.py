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
            return RouteDecision(
                route=FastRoute.WORKFLOW,
                rule_id="routing.workflow.empty_input",
                reason="Empty input is routed to workflow for safe handling.",
            )

        if self._contains_any(normalized, _WORKFLOW_PHRASES):
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
