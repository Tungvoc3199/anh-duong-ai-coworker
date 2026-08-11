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

