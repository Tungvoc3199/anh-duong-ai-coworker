# Task FR-1 — Fast Router v1

## Outcome

FR-1 triển khai Fast Router deterministic tại domain layer. Router phân loại mỗi chuỗi đầu vào thành đúng một trong bốn route: direct, memory, core_read hoặc workflow.

Phạm vi giữ nguyên:

- Không tích hợp FastAPI, network, database, shell hoặc LLM.
- Không gọi Memory Repository hay Core Repository.
- Không tạo Task.
- Không đưa ra hoặc tự cấp Approval.
- Không sửa OpenClaw, Telegram, 9Router, database schema, migration hoặc systemd.
- Async Worker vẫn tắt ở runtime.

## Contract

Public API:

~~~python
from app.routing import FastRoute, FastRouter, RouteDecision

decision: RouteDecision = FastRouter().route("Tiến độ Project Atlas thế nào?")
assert decision.route is FastRoute.CORE_READ
~~~

RouteDecision là immutable và chỉ chứa:

- route: FastRoute
- rule_id: str
- reason: str

Router chuẩn hóa Unicode deterministic bằng casefold, bỏ dấu tiếng Việt, thay punctuation bằng khoảng trắng và collapse whitespace. Thứ tự luật cố định:

1. Input rỗng hoặc chỉ có punctuation/whitespace → workflow.
2. Có action hoặc side-effect phrase rõ ràng → workflow.
3. Có ý định truy xuất thông tin đã lưu → memory.
4. Có ý định đọc trạng thái Project, Task hoặc Core → core_read.
5. Chào hỏi, cảm ơn, xác nhận hoặc feedback rất đơn giản thuộc allowlist → direct.
6. Không khớp hoặc còn mơ hồ → workflow.

Workflow có precedence cao hơn các tín hiệu còn lại. Vì vậy câu vừa yêu cầu tìm memory vừa sửa file vẫn đi workflow. Router chỉ phân luồng; Policy Engine tiếp tục là nguồn quyết định an toàn cuối cùng.

## Cây thư mục overlay

~~~text
anh-duong-core/
├── app/
│   └── routing/
│       ├── __init__.py
│       ├── fast_router.py
│       └── models.py
├── docs/
│   └── TASK_FR1_FAST_ROUTER.md
└── tests/
    ├── security/
    │   └── test_fast_router_determinism.py
    └── unit/
        └── test_fast_router.py
~~~

## Toàn bộ nội dung file tạo/sửa

Tất cả năm file source/test được ghi nguyên văn dưới đây. Tài liệu handoff này là container nên không tự lặp lại chính nó để tránh đệ quy vô hạn.

### app/routing/__init__.py

~~~python
from app.routing.fast_router import FastRouter
from app.routing.models import FastRoute, RouteDecision

__all__ = [
    "FastRoute",
    "FastRouter",
    "RouteDecision",
]
~~~

### app/routing/models.py

~~~python
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class FastRoute(StrEnum):
    DIRECT = "direct"
    MEMORY = "memory"
    CORE_READ = "core_read"
    WORKFLOW = "workflow"


class RouteDecision(BaseModel):
    """Immutable routing result; safety approval remains a Policy concern."""

    model_config = ConfigDict(frozen=True)

    route: FastRoute
    rule_id: str = Field(min_length=1)
    reason: str = Field(min_length=1)
~~~

### app/routing/fast_router.py

~~~python
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
            route=FastRoute.WORKFLOW,
            rule_id="routing.workflow.ambiguous_input",
            reason="Unknown or ambiguous input is routed to workflow for safe handling.",
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
~~~

### tests/unit/test_fast_router.py

~~~python
import pytest
from pydantic import ValidationError

from app.routing import FastRoute, FastRouter, RouteDecision


@pytest.mark.parametrize(
    "text",
    [
        "Xin chào!",
        "Chào buổi sáng, Ánh Dương.",
        "Chào bạn, khỏe không?",
        "Cảm ơn bạn.",
        "OK",
        "Đã rõ.",
        "Got it.",
        "Vâng, tôi hiểu rồi.",
        "Sounds good!",
        "Thanks so much.",
    ],
)
def test_simple_conversation_routes_direct(text: str) -> None:
    decision = FastRouter().route(text)

    assert decision.route is FastRoute.DIRECT


@pytest.mark.parametrize(
    "text",
    [
        "Hãy tìm trong bộ nhớ điều tôi đã lưu về Project Atlas.",
        "Bạn có nhớ tôi đã nói gì về ngân sách không?",
        "Cho tôi biết thông tin đã lưu về Project Atlas.",
        "Nhớ lại sở thích giao diện của tôi.",
        "Search memory for the deployment note.",
        "Recall my stored preference for dark mode.",
        "What have I saved about deployments?",
        "What did I say about the release date?",
    ],
)
def test_stored_information_requests_route_memory(text: str) -> None:
    decision = FastRouter().route(text)

    assert decision.route is FastRoute.MEMORY


@pytest.mark.parametrize(
    "text",
    [
        "Cho tôi xem trạng thái Core.",
        "Dự án Atlas thế nào?",
        "Tiến độ Project Atlas thế nào?",
        "Task FR-1 đang ở trạng thái nào?",
        "Kiểm tra health của Ánh Dương Core.",
        "How is Core?",
        "Show me the current Core status.",
        "What is the progress of project Atlas?",
    ],
)
def test_status_requests_route_core_read(text: str) -> None:
    decision = FastRouter().route(text)

    assert decision.route is FastRoute.CORE_READ


@pytest.mark.parametrize(
    "text",
    [
        "Hãy lập kế hoạch cho FR-1.",
        "Tạo file bao-cao.md.",
        "Sửa README và chạy pytest.",
        "Triển khai Fast Router.",
        "Build the new routing module.",
        "Delete the obsolete file.",
        "Send the status report by email.",
    ],
)
def test_action_requests_route_workflow(text: str) -> None:
    decision = FastRouter().route(text)

    assert decision.route is FastRoute.WORKFLOW


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   \t\n",
        "Màu tím.",
        "Could you help me with this?",
        "Phân tích việc này.",
    ],
)
def test_empty_or_ambiguous_requests_fail_closed(text: str) -> None:
    decision = FastRouter().route(text)

    assert decision.route is FastRoute.WORKFLOW


@pytest.mark.parametrize(
    "text",
    [
        "Cảm ơn, hãy tạo file báo cáo.",
        "Tìm trong memory rồi sửa README.",
        "Xem trạng thái Task FR-1 và cập nhật nó thành completed.",
    ],
)
def test_side_effect_intent_takes_precedence(text: str) -> None:
    decision = FastRouter().route(text)

    assert decision.route is FastRoute.WORKFLOW
    assert decision.rule_id == "routing.workflow.explicit_action"


def test_empty_input_uses_explicit_fail_closed_rule() -> None:
    decision = FastRouter().route(" \n\t ")

    assert decision == RouteDecision(
        route=FastRoute.WORKFLOW,
        rule_id="routing.workflow.empty_input",
        reason="Empty input is routed to workflow for safe handling.",
    )


def test_route_decision_is_immutable() -> None:
    decision = FastRouter().route("Xin chào")

    with pytest.raises(ValidationError):
        decision.route = FastRoute.WORKFLOW


def test_routing_package_exports_public_contract() -> None:
    from app.routing import FastRoute as ExportedFastRoute
    from app.routing import FastRouter as ExportedFastRouter
    from app.routing import RouteDecision as ExportedRouteDecision

    assert ExportedFastRoute is FastRoute
    assert ExportedFastRouter is FastRouter
    assert ExportedRouteDecision is RouteDecision
~~~

### tests/security/test_fast_router_determinism.py

~~~python
import ast
import inspect

import pytest

import app.routing.fast_router as fast_router_module
from app.routing import FastRoute, FastRouter, RouteDecision


@pytest.mark.parametrize(
    "text, expected_route",
    [
        ("Xin chào!", FastRoute.DIRECT),
        ("Tìm trong bộ nhớ ghi chú release.", FastRoute.MEMORY),
        ("Trạng thái Core hiện tại thế nào?", FastRoute.CORE_READ),
        ("Chạy test cho dự án.", FastRoute.WORKFLOW),
        ("Không rõ.", FastRoute.WORKFLOW),
        ("", FastRoute.WORKFLOW),
    ],
)
def test_repeated_requests_are_deterministic(
    text: str,
    expected_route: FastRoute,
) -> None:
    router = FastRouter()
    decisions = [router.route(text) for _ in range(100)]

    assert all(decision == decisions[0] for decision in decisions)
    assert decisions[0].route is expected_route


def test_fast_router_imports_no_io_or_model_frameworks() -> None:
    source = inspect.getsource(fast_router_module)
    syntax_tree = ast.parse(source)

    imported_roots: set[str] = set()
    for node in ast.walk(syntax_tree):
        if isinstance(node, ast.Import):
            imported_roots.update(
                alias.name.split(".", maxsplit=1)[0]
                for alias in node.names
            )
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".", maxsplit=1)[0])

    forbidden_modules = {
        "anthropic",
        "fastapi",
        "httpx",
        "openai",
        "requests",
        "socket",
        "sqlalchemy",
        "subprocess",
    }
    assert imported_roots.isdisjoint(forbidden_modules)


def test_route_decision_cannot_grant_or_require_approval() -> None:
    assert set(RouteDecision.model_fields) == {
        "route",
        "rule_id",
        "reason",
    }
~~~

## Verification

### Trước thay đổi

- Không có metadata .git trong thư mục repo nên không thể kết luận dirty/clean bằng git status. Không commit hoặc push được thực hiện.
- Sáu target FR-1 đều chưa tồn tại.
- Backup root tạm: C:\tmp\anh-duong-fr1-backup-20260731.
- Baseline pytest: 168 passed, 1 warning có sẵn.
- Baseline Ruff: All checks passed.
- Baseline Mypy: no issues in 47 source files.
- Baseline Compileall: exit 0.

### TDD

- RED vòng 1: targeted tests dừng collection với ModuleNotFoundError: No module named app.routing.
- GREEN vòng 1: 45 passed in 1.02s.
- Self-review RED: 7 failed và 37 passed cho các phrase contract còn thiếu.
- GREEN cuối: 52 passed in 1.76s.
- Targeted Ruff: PASS.
- Targeted Mypy: no issues in 3 source files.

### Regression cuối

- pytest -q: 220 passed, 1 warning có sẵn trong 25.44s.
- ruff check .: All checks passed.
- mypy app: no issues in 50 source files.
- python -m compileall -q app tests alembic: exit 0.

### Runtime

- anh-duong-core.service: active/running.
- Safety drop-in vẫn được systemd nạp từ /etc/systemd/system/anh-duong-core.service.d/99-checkpoint-4.2-g0-safe.conf.
- GET /health: HTTP 200, status ok.
- GET /ready: HTTP 200, database ok.
- Alembic current: 0003 (head).
- Process Core hiệu lực: ANH_DUONG_ASYNC_WORKER_ENABLED=false.
- Không restart service, deploy, migration hoặc sửa systemd.

### Artifacts

- ZIP overlay: /mnt/f/AIOS/anh-duong-checkpoints/anh-duong-core-FR1-overlay.zip
- Checkpoint log duy nhất: /mnt/f/AIOS/anh-duong-checkpoints/checkpoint-FR1-one-shot.log

## Rollback

Tất cả file FR-1 đều là file mới. Trước khi rollback, xác minh đúng sáu đường dẫn dưới đây. Sau đó có thể xóa chính xác các file này; không cần database downgrade hay thay đổi systemd:

~~~powershell
Set-Location F:\AIOS\anh-duong-core

Remove-Item -LiteralPath @(
    'app\routing\__init__.py',
    'app\routing\fast_router.py',
    'app\routing\models.py',
    'tests\unit\test_fast_router.py',
    'tests\security\test_fast_router_determinism.py',
    'docs\TASK_FR1_FAST_ROUTER.md'
) -Force

Remove-Item -LiteralPath 'app\routing' -Force
~~~

ZIP và checkpoint log là artifact bàn giao độc lập; chỉ xóa chúng khi không còn cần rollback/audit.
