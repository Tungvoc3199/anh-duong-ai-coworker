# Task CR-1 — Capability/Skill Router v1

## Outcome

CR-1 triển khai Capability/Skill Router deterministic tại domain layer. Router nhận
`RouteDecision` đã có từ Fast Router FR-1 cùng nội dung yêu cầu gốc và trả đúng một
`CapabilityDecision`; router chỉ phân loại, không thực thi capability hoặc skill.

Phạm vi được giữ nguyên:

- Không dùng LLM, network, database, filesystem, shell, clock hoặc random.
- Không gọi Memory, Project, Task, workflow executor, Codex hoặc OpenClaw.
- Không quyết định ALLOW, DENY hoặc APPROVAL; Policy Engine vẫn là nguồn quyết định
  an toàn cuối cùng.
- Không nối API, Telegram, Context Builder hoặc 9Router.
- Không sửa schema, migration, systemd hoặc cấu hình Async Worker.

## Capability contract

Public API:

~~~python
from app.capabilities import CapabilityDecision, CapabilityRouter
from app.routing import FastRouter

request = "Task FR-1 đang ở trạng thái nào?"
route_decision = FastRouter().route(request)
decision: CapabilityDecision = CapabilityRouter().route(route_decision, request)
assert decision.capability == "task_read"
~~~

`CapabilityKind` có đúng mười một giá trị:

1. `conversational_response`
2. `memory_search`
3. `project_read`
4. `task_read`
5. `core_status_read`
6. `planning`
7. `file_operation`
8. `code_operation`
9. `external_communication`
10. `system_operation`
11. `unknown_workflow`

`CapabilityDecision` immutable và chỉ chứa:

- `capability: CapabilityKind`
- `source_route: FastRoute`
- `reason_code: str`
- `matched_signals: tuple[str, ...]`

Không có `PolicyDecision`, `ApprovalDecision`, executor hoặc trường cấp quyền.

## Precedence rules

1. Input rỗng → `unknown_workflow` với reason code fail-closed riêng.
2. `RouteDecision` không khớp chính xác kết quả FR-1 cho cùng request →
   `unknown_workflow`; `source_route` giữ route được cung cấp để audit.
3. Route `direct` hợp lệ → chỉ `conversational_response`.
4. Route `memory` hợp lệ → chỉ `memory_search`.
5. Route `core_read` dùng specificity: Task → Project → Core.
6. Route `workflow` dùng thứ tự: System → External Communication → Code → File →
   Planning → Unknown.

System/external side effect không thể bị hạ thành read-only hoặc planning. Code/file
được xét trước planning. Signal matching dùng Unicode NFKD, casefold, bỏ dấu tiếng
Việt, token boundary và tuple theo thứ tự cố định nên cùng input luôn cho cùng output.

## Cây thư mục overlay

~~~text
anh-duong-core/
├── app/
│   └── capabilities/
│       ├── __init__.py
│       ├── models.py
│       └── router.py
├── docs/
│   └── TASK_CR1_CAPABILITY_ROUTER.md
└── tests/
    ├── security/
    │   └── test_capability_router_determinism.py
    └── unit/
        └── test_capability_router.py
~~~

## Toàn bộ nội dung file tạo/sửa

Tất cả năm file source/test CR-1 được ghi nguyên văn dưới đây. Tài liệu handoff này là
container nên không tự lặp lại chính nó để tránh đệ quy vô hạn. Mini-spec và kế hoạch
triển khai nằm tại `docs/superpowers/specs/` và `docs/superpowers/plans/`.

### app/capabilities/__init__.py

~~~python
from app.capabilities.models import CapabilityDecision, CapabilityKind
from app.capabilities.router import CapabilityRouter

__all__ = [
    "CapabilityDecision",
    "CapabilityKind",
    "CapabilityRouter",
]
~~~

### app/capabilities/models.py

~~~python
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from app.routing.models import FastRoute


class CapabilityKind(StrEnum):
    CONVERSATIONAL_RESPONSE = "conversational_response"
    MEMORY_SEARCH = "memory_search"
    PROJECT_READ = "project_read"
    TASK_READ = "task_read"
    CORE_STATUS_READ = "core_status_read"
    PLANNING = "planning"
    FILE_OPERATION = "file_operation"
    CODE_OPERATION = "code_operation"
    EXTERNAL_COMMUNICATION = "external_communication"
    SYSTEM_OPERATION = "system_operation"
    UNKNOWN_WORKFLOW = "unknown_workflow"


class CapabilityDecision(BaseModel):
    """Immutable classification result without Policy or Approval authority."""

    model_config = ConfigDict(frozen=True)

    capability: CapabilityKind
    source_route: FastRoute
    reason_code: str = Field(min_length=1)
    matched_signals: tuple[str, ...]
~~~

### app/capabilities/router.py

~~~python
from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable

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
)

_EXTERNAL_INHERENT_SIGNALS = (
    "du lieu ra ngoai",
    "external communication",
    "publish",
    "upload",
    "post",
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
        if not normalized:
            return self._decision(
                CapabilityKind.UNKNOWN_WORKFLOW,
                route_decision.route,
                "capability.workflow.empty_input",
            )

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
        if route_decision.route is FastRoute.MEMORY:
            return self._decision(
                CapabilityKind.MEMORY_SEARCH,
                route_decision.route,
                "capability.memory.memory_search",
                ("route:memory",),
            )
        if route_decision.route is FastRoute.CORE_READ:
            return self._route_core_read(route_decision.route, normalized)
        return self._route_workflow(route_decision.route, normalized)

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
    ) -> CapabilityDecision:
        system_signals = self._compound_signals(
            normalized,
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

        external_signals = self._compound_signals(
            normalized,
            "external",
            _EXTERNAL_INHERENT_SIGNALS,
            _EXTERNAL_ACTION_SIGNALS,
            _EXTERNAL_TARGET_SIGNALS,
        )
        if external_signals:
            return self._decision(
                CapabilityKind.EXTERNAL_COMMUNICATION,
                source_route,
                "capability.workflow.external_communication",
                external_signals,
            )

        code_signals = self._compound_signals(
            normalized,
            "code",
            _CODE_INHERENT_SIGNALS,
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
            normalized,
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
            character
            for character in decomposed
            if not unicodedata.combining(character)
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
~~~

### tests/unit/test_capability_router.py

~~~python
import pytest
from pydantic import ValidationError

from app.capabilities import (
    CapabilityDecision,
    CapabilityKind,
    CapabilityRouter,
)
from app.routing import FastRoute, FastRouter, RouteDecision


def _route(request: str) -> CapabilityDecision:
    fast_decision = FastRouter().route(request)
    return CapabilityRouter().route(fast_decision, request)


def test_capability_kind_contains_exact_v1_contract() -> None:
    assert {kind.value for kind in CapabilityKind} == {
        "conversational_response",
        "memory_search",
        "project_read",
        "task_read",
        "core_status_read",
        "planning",
        "file_operation",
        "code_operation",
        "external_communication",
        "system_operation",
        "unknown_workflow",
    }


@pytest.mark.parametrize(
    ("text", "expected_capability", "expected_route"),
    [
        (
            "Xin chào!",
            CapabilityKind.CONVERSATIONAL_RESPONSE,
            FastRoute.DIRECT,
        ),
        (
            "Bạn có nhớ tôi đã nói gì về ngân sách không?",
            CapabilityKind.MEMORY_SEARCH,
            FastRoute.MEMORY,
        ),
        (
            "Tiến độ Project Atlas thế nào?",
            CapabilityKind.PROJECT_READ,
            FastRoute.CORE_READ,
        ),
        (
            "Task FR-1 đang ở trạng thái nào?",
            CapabilityKind.TASK_READ,
            FastRoute.CORE_READ,
        ),
        (
            "Kiểm tra health của Ánh Dương Core.",
            CapabilityKind.CORE_STATUS_READ,
            FastRoute.CORE_READ,
        ),
        (
            "Hãy lập kế hoạch cho CR-1.",
            CapabilityKind.PLANNING,
            FastRoute.WORKFLOW,
        ),
        (
            "Tạo file báo cáo.md.",
            CapabilityKind.FILE_OPERATION,
            FastRoute.WORKFLOW,
        ),
        (
            "Chạy pytest cho app.",
            CapabilityKind.CODE_OPERATION,
            FastRoute.WORKFLOW,
        ),
        (
            "Gửi báo cáo qua email.",
            CapabilityKind.EXTERNAL_COMMUNICATION,
            FastRoute.WORKFLOW,
        ),
        (
            "Khởi động lại service Core.",
            CapabilityKind.SYSTEM_OPERATION,
            FastRoute.WORKFLOW,
        ),
        (
            "Phân tích việc này.",
            CapabilityKind.UNKNOWN_WORKFLOW,
            FastRoute.WORKFLOW,
        ),
    ],
)
def test_routes_all_v1_capabilities(
    text: str,
    expected_capability: CapabilityKind,
    expected_route: FastRoute,
) -> None:
    decision = _route(text)

    assert decision.capability is expected_capability
    assert decision.source_route is expected_route
    assert decision.reason_code
    if expected_capability is not CapabilityKind.UNKNOWN_WORKFLOW:
        assert decision.matched_signals


@pytest.mark.parametrize(
    ("text", "expected_capability"),
    [
        (
            "Trạng thái Task FR-1 của Project Atlas thế nào?",
            CapabilityKind.TASK_READ,
        ),
        (
            "Trạng thái Project Atlas trên Ánh Dương Core thế nào?",
            CapabilityKind.PROJECT_READ,
        ),
    ],
)
def test_core_read_uses_entity_specificity_precedence(
    text: str,
    expected_capability: CapabilityKind,
) -> None:
    assert _route(text).capability is expected_capability


@pytest.mark.parametrize(
    ("text", "expected_capability"),
    [
        (
            "Lập kế hoạch khởi động lại service rồi gửi email.",
            CapabilityKind.SYSTEM_OPERATION,
        ),
        (
            "Chạy pytest rồi gửi kết quả qua Slack.",
            CapabilityKind.EXTERNAL_COMMUNICATION,
        ),
        (
            "Lập kế hoạch sửa code và chạy pytest.",
            CapabilityKind.CODE_OPERATION,
        ),
        (
            "Lập kế hoạch tạo file báo cáo.md.",
            CapabilityKind.FILE_OPERATION,
        ),
    ],
)
def test_workflow_precedence_protects_side_effects(
    text: str,
    expected_capability: CapabilityKind,
) -> None:
    assert _route(text).capability is expected_capability


@pytest.mark.parametrize(
    ("text", "expected_capability"),
    [
        ("Deploy the API service.", CapabilityKind.SYSTEM_OPERATION),
        ("Publish the report externally.", CapabilityKind.EXTERNAL_COMMUNICATION),
        ("Generate a Python module.", CapabilityKind.CODE_OPERATION),
        ("List files in the reports folder.", CapabilityKind.FILE_OPERATION),
        ("Break down Task CR-1 into steps.", CapabilityKind.PLANNING),
        ("Call the deployment webhook.", CapabilityKind.EXTERNAL_COMMUNICATION),
    ],
)
def test_workflow_contract_action_variants(
    text: str,
    expected_capability: CapabilityKind,
) -> None:
    assert _route(text).capability is expected_capability

def test_empty_input_fails_closed() -> None:
    decision = _route(" \n\t ")

    assert decision == CapabilityDecision(
        capability=CapabilityKind.UNKNOWN_WORKFLOW,
        source_route=FastRoute.WORKFLOW,
        reason_code="capability.workflow.empty_input",
        matched_signals=(),
    )


@pytest.mark.parametrize(
    "route_decision",
    [
        RouteDecision(
            route=FastRoute.DIRECT,
            rule_id="routing.direct.simple_conversation",
            reason="The request is a simple conversational response.",
        ),
        RouteDecision(
            route=FastRoute.WORKFLOW,
            rule_id="forged.rule",
            reason="Forged upstream decision.",
        ),
    ],
)
def test_inconsistent_fast_router_decision_fails_closed(
    route_decision: RouteDecision,
) -> None:
    decision = CapabilityRouter().route(route_decision, "Tạo file report.md.")

    assert decision.capability is CapabilityKind.UNKNOWN_WORKFLOW
    assert decision.source_route is route_decision.route
    assert decision.reason_code == "capability.workflow.inconsistent_route"
    assert decision.matched_signals == ()


def test_capability_decision_is_immutable() -> None:
    decision = _route("Xin chào!")

    with pytest.raises(ValidationError):
        decision.capability = CapabilityKind.UNKNOWN_WORKFLOW


def test_capability_package_exports_public_contract() -> None:
    from app.capabilities import CapabilityDecision as ExportedDecision
    from app.capabilities import CapabilityKind as ExportedKind
    from app.capabilities import CapabilityRouter as ExportedRouter

    assert ExportedDecision is CapabilityDecision
    assert ExportedKind is CapabilityKind
    assert ExportedRouter is CapabilityRouter
~~~

### tests/security/test_capability_router_determinism.py

~~~python
import ast
import inspect

import pytest

import app.capabilities.router as capability_router_module
from app.capabilities import CapabilityDecision, CapabilityKind, CapabilityRouter
from app.routing import FastRouter


@pytest.mark.parametrize(
    "text",
    [
        "Xin chào!",
        "Bạn có nhớ tôi đã nói gì về ngân sách không?",
        "Tiến độ Project Atlas thế nào?",
        "Task FR-1 đang ở trạng thái nào?",
        "Kiểm tra health của Ánh Dương Core.",
        "Hãy lập kế hoạch cho CR-1.",
        "Tạo file báo cáo.md.",
        "Chạy pytest cho app.",
        "Gửi báo cáo qua email.",
        "Khởi động lại service Core.",
        "Phân tích việc này.",
        "",
    ],
)
def test_repeated_capability_decisions_are_deterministic(text: str) -> None:
    route_decision = FastRouter().route(text)
    router = CapabilityRouter()

    decisions = [router.route(route_decision, text) for _ in range(100)]

    assert all(decision == decisions[0] for decision in decisions)


@pytest.mark.parametrize(
    ("text", "expected_capability"),
    [
        (
            "Kiểm tra health rồi khởi động lại Core.",
            CapabilityKind.SYSTEM_OPERATION,
        ),
        (
            "Tìm trong memory rồi gửi nội dung qua Telegram.",
            CapabilityKind.EXTERNAL_COMMUNICATION,
        ),
        (
            "Xem trạng thái Task rồi sửa bug và chạy test.",
            CapabilityKind.CODE_OPERATION,
        ),
        (
            "Xem trạng thái Project rồi tạo file báo cáo.",
            CapabilityKind.FILE_OPERATION,
        ),
    ],
)
def test_side_effect_intent_is_never_downgraded_to_read_only(
    text: str,
    expected_capability: CapabilityKind,
) -> None:
    route_decision = FastRouter().route(text)

    decision = CapabilityRouter().route(route_decision, text)

    assert decision.capability is expected_capability


def test_capability_router_imports_no_io_or_nondeterministic_modules() -> None:
    source = inspect.getsource(capability_router_module)
    syntax_tree = ast.parse(source)

    imported_roots: set[str] = set()
    for node in ast.walk(syntax_tree):
        if isinstance(node, ast.Import):
            imported_roots.update(
                alias.name.split(".", maxsplit=1)[0] for alias in node.names
            )
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".", maxsplit=1)[0])

    forbidden_modules = {
        "anthropic",
        "asyncio",
        "datetime",
        "fastapi",
        "httpx",
        "openai",
        "os",
        "pathlib",
        "random",
        "requests",
        "socket",
        "sqlalchemy",
        "subprocess",
        "time",
    }
    assert imported_roots.isdisjoint(forbidden_modules)


def test_capability_decision_has_no_policy_or_approval_authority() -> None:
    assert set(CapabilityDecision.model_fields) == {
        "capability",
        "source_route",
        "reason_code",
        "matched_signals",
    }
~~~

## Verification

### Trước thay đổi

- Pytest: 220 passed, 1 warning có sẵn.
- Ruff: All checks passed.
- Mypy: no issues in 50 source files.
- Compileall: exit 0.

### TDD

- RED ban đầu: collection dừng với `ModuleNotFoundError: app.capabilities`.
- GREEN vòng đầu: 41 targeted tests passed.
- Self-review RED: 6 action variants failed đúng vì chưa có signal.
- GREEN action variants: 6 passed.
- Targeted cuối: 47 passed.

### Regression cuối

- `pytest -q`: 267 passed, 1 warning có sẵn trong 20.70s.
- `ruff check .`: All checks passed.
- `mypy app`: no issues in 53 source files.
- `python -m compileall -q app tests alembic`: exit 0.

### Runtime

- `anh-duong-core.service`: active/running.
- Safety drop-in vẫn được systemd nạp từ
  `/etc/systemd/system/anh-duong-core.service.d/99-checkpoint-4.2-g0-safe.conf`.
- `GET /health`: HTTP 200, status ok.
- `GET /ready`: HTTP 200, database ok.
- Alembic current: `0003 (head)`.
- Process Core PID 18937 hiệu lực: `ANH_DUONG_ASYNC_WORKER_ENABLED=false`.
- Không restart service, deploy, migration hoặc sửa systemd.

### Artifacts

- ZIP overlay: `/mnt/f/AIOS/anh-duong-checkpoints/anh-duong-core-CR1-overlay.zip`.
- Checkpoint log duy nhất:
  `/mnt/f/AIOS/anh-duong-checkpoints/checkpoint-CR1-one-shot.log`.
- Không commit hoặc push; checkout hiện tại không có metadata `.git` khả dụng.

## Rollback

Tất cả file CR-1 đều là file mới. Trước khi rollback, xác minh đúng tám đường dẫn dưới
đây. Sau đó có thể xóa chính xác các file này; không cần database downgrade, restart
service hoặc thay đổi systemd:

~~~powershell
Set-Location F:\AIOS\anh-duong-core

Remove-Item -LiteralPath @(
    'app\capabilities\__init__.py',
    'app\capabilities\models.py',
    'app\capabilities\router.py',
    'tests\unit\test_capability_router.py',
    'tests\security\test_capability_router_determinism.py',
    'docs\TASK_CR1_CAPABILITY_ROUTER.md',
    'docs\superpowers\specs\2026-07-31-cr1-capability-router-design.md',
    'docs\superpowers\plans\2026-07-31-cr1-capability-router.md'
) -Force

Remove-Item -LiteralPath 'app\capabilities' -Force
Remove-Item -LiteralPath 'F:\AIOS\anh-duong-checkpoints\anh-duong-core-CR1-overlay.zip' -Force
Remove-Item -LiteralPath 'F:\AIOS\anh-duong-checkpoints\checkpoint-CR1-one-shot.log' -Force
~~~

