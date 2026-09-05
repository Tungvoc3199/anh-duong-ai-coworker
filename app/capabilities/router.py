from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable

from app.capabilities.intent_contract import build_visual_intent_contract
from app.capabilities.models import CapabilityDecision, CapabilityKind
from app.routing.fast_router import FastRouter
from app.routing.models import FastRoute, RouteDecision

_TASK_SIGNALS = ("task", "nhiem vu")
_PROJECT_SIGNALS = ("project", "du an")
_CORE_SIGNALS = ("anh duong core", "core", "anh duong")

_SYSTEM_INHERENT_SIGNALS = (
    "khoi dong lai",
    "restart",
    "cai dat",
    "install",
    "go cai dat",
    "uninstall",
)
_SYSTEM_ACTION_SIGNALS = (
    "cau hinh",
    "configure",
    "sua",
    "modify",
    "change",
    "cap nhat",
    "update",
    "deploy",
    "trien khai",
    "mo",
    "open",
    "chay",
    "run",
    "kiem tra",
    "check",
    "xem",
    "view",
    "huong dan",
    "cach",
    "nhu nao",
    "the nao",
    "o dau",
    "cho anh lenh",
    "cho toi lenh",
)
_SYSTEM_TARGET_SIGNALS = (
    "runtime config",
    "system config",
    "cau hinh runtime",
    "cau hinh he thong",
    "systemd",
    "service",
    "package",
    "dependency",
    "dependencies",
    "he thong",
    "system",
    "runtime",
    "openclaw",
    "docker",
    "docker compose",
    "wsl",
    "linux",
    "container",
    "gateway",
    "9router",
    "browser",
    "chrome",
    "cli",
    "terminal",
    "shell",
)

_EXTERNAL_INHERENT_SIGNALS = (
    "du lieu ra ngoai",
    "external communication",
    "publish",
    "upload",
)
_EXTERNAL_ACTION_SIGNALS = (
    "gui",
    "send",
    "publish",
    "dang",
    "post",
    "upload",
    "nhan tin",
    "message",
    "call",
    "goi",
    "notify",
    "thong bao",
)
_EXTERNAL_TARGET_SIGNALS = (
    "email",
    "telegram",
    "slack",
    "teams",
    "outlook",
    "webhook",
    "facebook",
    "instagram",
    "tiktok",
    "social media",
    "tin nhan",
    "message",
)

_CODE_INHERENT_SIGNALS = (
    "pytest",
    "ruff",
    "mypy",
    "compileall",
    "unit test",
    "integration test",
    "test suite",
    "debug",
    "refactor",
    "fix bug",
    "sua loi",
    "build",
    "compile",
    "lint",
)
_CODE_ACTION_SIGNALS = (
    "viet",
    "write",
    "sua",
    "edit",
    "cap nhat",
    "update",
    "tao",
    "create",
    "chay",
    "run",
    "trien khai",
    "implement",
    "phan tich",
    "analyze",
    "review",
    "generate",
    "execute",
    "thuc hien",
    "doc",
    "read",
)
_CODE_TARGET_SIGNALS = (
    "code",
    "ma nguon",
    "python",
    "javascript",
    "typescript",
    "module",
    "function",
    "class",
    "api",
    "pytest",
    "test",
    "tests",
    "bug",
    "app",
    "application",
    "py",
    "js",
    "ts",
)

_FILE_ACTION_SIGNALS = (
    "doc",
    "read",
    "tao",
    "create",
    "sua",
    "edit",
    "cap nhat",
    "update",
    "ghi",
    "write",
    "xoa",
    "delete",
    "remove",
    "sao chep",
    "copy",
    "di chuyen",
    "move",
    "doi ten",
    "rename",
    "list",
    "show",
    "view",
    "open",
    "xem",
    "mo",
    "generate",
)
_FILE_TARGET_SIGNALS = (
    "file",
    "tep",
    "folder",
    "directory",
    "thu muc",
    "readme",
    "markdown",
    "md",
    "json",
    "yaml",
    "yml",
    "toml",
    "csv",
    "txt",
    "pdf",
    "docx",
    "xlsx",
)

_VISUAL_PROMPT_ACTION_SIGNALS = (
    "dung",
    "su dung",
    "lam",
    "tao",
    "soan",
    "viet",
    "generate",
    "compose",
    "make",
    "build",
)
_VISUAL_PROMPT_TARGET_SIGNALS = (
    "prompt anh",
    "prompt hinh anh",
    "visual prompt",
    "image prompt",
)
_VISUAL_IMAGE_ACTION_SIGNALS = (
    "dung",
    "su dung",
    "lam",
    "tao",
    "create",
    "generate",
    "make",
    "build",
)
_VISUAL_IMAGE_TARGET_PATTERN = re.compile(
    r"(?<!\w)(?:ảnh|hình(?:\s+ảnh)?|hinh(?:\s+anh)?|image|photo|picture|artwork|poster|banner|thumbnail)(?!\w)",
    re.IGNORECASE,
)

_PLANNING_SIGNALS = (
    "lap ke hoach",
    "phan ra cong viec",
    "phan ra",
    "chia nho cong viec",
    "plan",
    "planning",
    "roadmap",
    "decompose",
    "break down",
)


class CapabilityRouter:
    """Pure deterministic router from an FR-1 decision to one capability."""

    def route(
        self,
        route_decision: RouteDecision,
        request: str,
    ) -> CapabilityDecision:
        normalized = self._normalize(request)
        if FastRouter().route(request) != route_decision:
            return self._decision(
                CapabilityKind.UNKNOWN_WORKFLOW,
                route_decision.route,
                "capability.workflow.inconsistent_route",
            )

        if route_decision.route is FastRoute.DIRECT:
            return self._decision(
                CapabilityKind.CONVERSATIONAL_RESPONSE,
                route_decision.route,
                "capability.direct.conversational_response",
                ("route:direct",),
            )

        if not normalized:
            return self._decision(
                CapabilityKind.UNKNOWN_WORKFLOW,
                route_decision.route,
                "capability.workflow.empty_input",
            )
        if route_decision.route is FastRoute.MEMORY:
            return self._decision(
                CapabilityKind.MEMORY_SEARCH,
                route_decision.route,
                "capability.memory.memory_search",
                ("route:memory",),
            )
        if route_decision.route is FastRoute.CORE_READ:
            return self._route_core_read(route_decision.route, normalized)
        return self._route_workflow(route_decision.route, normalized, request)

    def _route_core_read(
        self,
        source_route: FastRoute,
        normalized: str,
    ) -> CapabilityDecision:
        task_signals = self._signals(normalized, "core:task", _TASK_SIGNALS)
        if task_signals:
            return self._decision(
                CapabilityKind.TASK_READ,
                source_route,
                "capability.core_read.task",
                task_signals,
            )

        project_signals = self._signals(
            normalized,
            "core:project",
            _PROJECT_SIGNALS,
        )
        if project_signals:
            return self._decision(
                CapabilityKind.PROJECT_READ,
                source_route,
                "capability.core_read.project",
                project_signals,
            )

        core_signals = self._signals(normalized, "core:status", _CORE_SIGNALS)
        if core_signals:
            return self._decision(
                CapabilityKind.CORE_STATUS_READ,
                source_route,
                "capability.core_read.status",
                core_signals,
            )

        return self._decision(
            CapabilityKind.UNKNOWN_WORKFLOW,
            source_route,
            "capability.workflow.unrecognized_core_read",
        )

    def _route_workflow(
        self,
        source_route: FastRoute,
        normalized: str,
        request: str,
    ) -> CapabilityDecision:
        visual_actions = self._signals(normalized, "visual:action", _VISUAL_PROMPT_ACTION_SIGNALS)
        visual_targets = self._signals(normalized, "visual:target", _VISUAL_PROMPT_TARGET_SIGNALS)
        image_action_signals = self._signals(
            normalized, "visual:image_action", _VISUAL_IMAGE_ACTION_SIGNALS
        )
        visual_image_requested = bool(image_action_signals) and self._visual_image_requested(
            request
        )
        visual_intent = build_visual_intent_contract(request) if visual_image_requested else None
        side_effect_source = (
            visual_intent.side_effect_text if visual_intent is not None else request
        )
        side_effect_text = (
            self._visual_side_effect_text(side_effect_source)
            if (visual_actions and visual_targets) or visual_image_requested
            else normalized
        )
        system_signals = self._compound_signals(
            side_effect_text,
            "system",
            _SYSTEM_INHERENT_SIGNALS,
            _SYSTEM_ACTION_SIGNALS,
            _SYSTEM_TARGET_SIGNALS,
        )
        if system_signals:
            return self._decision(
                CapabilityKind.SYSTEM_OPERATION,
                source_route,
                "capability.workflow.system_operation",
                system_signals,
            )

        external_signals = (
            visual_intent.external_signals
            if visual_intent is not None
            else self._compound_signals(
                side_effect_text,
                "external",
                _EXTERNAL_INHERENT_SIGNALS,
                _EXTERNAL_ACTION_SIGNALS,
                _EXTERNAL_TARGET_SIGNALS,
            )
        )
        if external_signals:
            return self._decision(
                CapabilityKind.EXTERNAL_COMMUNICATION,
                source_route,
                "capability.workflow.external_communication",
                external_signals,
            )

        code_inherent = (
            tuple(item for item in _CODE_INHERENT_SIGNALS if item not in {"build", "compile"})
            if visual_actions and visual_targets
            else _CODE_INHERENT_SIGNALS
        )
        code_signals = self._compound_signals(
            side_effect_text,
            "code",
            code_inherent,
            _CODE_ACTION_SIGNALS,
            _CODE_TARGET_SIGNALS,
        )
        if code_signals:
            return self._decision(
                CapabilityKind.CODE_OPERATION,
                source_route,
                "capability.workflow.code_operation",
                code_signals,
            )

        file_signals = self._compound_signals(
            side_effect_text,
            "file",
            (),
            _FILE_ACTION_SIGNALS,
            _FILE_TARGET_SIGNALS,
        )
        if file_signals:
            return self._decision(
                CapabilityKind.FILE_OPERATION,
                source_route,
                "capability.workflow.file_operation",
                file_signals,
            )

        if visual_image_requested:
            return self._decision(
                CapabilityKind.VISUAL_IMAGE_GENERATE,
                source_route,
                "capability.workflow.visual_image_generate",
                image_action_signals + ("visual:target:image",),
            )

        if visual_actions and visual_targets:
            return self._decision(
                CapabilityKind.VISUAL_PROMPT_COMPOSE,
                source_route,
                "capability.workflow.visual_prompt_compose",
                visual_actions + visual_targets,
            )

        planning_signals = self._signals(
            normalized,
            "planning",
            _PLANNING_SIGNALS,
        )
        if planning_signals:
            return self._decision(
                CapabilityKind.PLANNING,
                source_route,
                "capability.workflow.planning",
                planning_signals,
            )

        return self._decision(
            CapabilityKind.UNKNOWN_WORKFLOW,
            source_route,
            "capability.workflow.unknown",
        )

    @classmethod
    def _visual_image_requested(cls, request: str) -> bool:
        normalized = cls._normalize(request)
        if any(
            cls._contains_phrase(normalized, phrase) for phrase in _VISUAL_PROMPT_TARGET_SIGNALS
        ):
            return False
        target_text = re.sub(
            r"\b(?:cấu|cau)\s+hình\b",
            " ",
            request,
            flags=re.IGNORECASE,
        )
        if _VISUAL_IMAGE_TARGET_PATTERN.search(target_text) is not None:
            return True
        return (
            re.search(
                r"\b(?:tao|lam|create|generate|make|build)\s+anh\b",
                normalized,
            )
            is not None
        )

    @classmethod
    def _visual_side_effect_text(cls, request: str) -> str:
        without_copy = re.sub(r'["“][^"”]*["”]', " ", request)
        folded = unicodedata.normalize("NFKD", without_copy.casefold())
        folded = "".join(c for c in folded if not unicodedata.combining(c)).replace("đ", "d")
        pieces = re.split(r"[.!?;\n]+|\s+-\s+|,|\bnhung\b|\bbut\b|\bhowever\b", folded)
        positive: list[str] = []
        for piece in pieces:
            normalized_piece = cls._normalize(piece)
            if not normalized_piece:
                continue
            tokens = normalized_piece.split()
            negated = [i for i, token in enumerate(tokens) if token in {"khong", "no"}]
            if negated:
                tokens = tokens[: min(negated)]
            if tokens:
                positive.append(" ".join(tokens))
        return " ".join(positive)

    @classmethod
    def _compound_signals(
        cls,
        normalized: str,
        namespace: str,
        inherent_phrases: Iterable[str],
        action_phrases: Iterable[str],
        target_phrases: Iterable[str],
    ) -> tuple[str, ...]:
        inherent = cls._signals(
            normalized,
            f"{namespace}:inherent",
            inherent_phrases,
        )
        actions = cls._signals(
            normalized,
            f"{namespace}:action",
            action_phrases,
        )
        targets = cls._signals(
            normalized,
            f"{namespace}:target",
            target_phrases,
        )
        if inherent:
            return inherent + targets
        if actions and targets:
            return actions + targets
        return ()

    @classmethod
    def _signals(
        cls,
        normalized: str,
        namespace: str,
        phrases: Iterable[str],
    ) -> tuple[str, ...]:
        return tuple(
            f"{namespace}:{phrase.replace(' ', '_')}"
            for phrase in phrases
            if cls._contains_phrase(normalized, phrase)
        )

    @staticmethod
    def _contains_phrase(normalized: str, phrase: str) -> bool:
        return f" {phrase} " in f" {normalized} "

    @staticmethod
    def _normalize(request: str) -> str:
        decomposed = unicodedata.normalize("NFKD", request.casefold())
        without_marks = "".join(
            character for character in decomposed if not unicodedata.combining(character)
        ).replace("đ", "d")
        return " ".join(re.sub(r"[^a-z0-9]+", " ", without_marks).split())

    @staticmethod
    def _decision(
        capability: CapabilityKind,
        source_route: FastRoute,
        reason_code: str,
        matched_signals: tuple[str, ...] = (),
    ) -> CapabilityDecision:
        return CapabilityDecision(
            capability=capability,
            source_route=source_route,
            reason_code=reason_code,
            matched_signals=matched_signals,
        )
