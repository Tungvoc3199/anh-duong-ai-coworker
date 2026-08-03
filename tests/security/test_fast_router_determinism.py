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
        ("Không rõ.", FastRoute.DIRECT),
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
