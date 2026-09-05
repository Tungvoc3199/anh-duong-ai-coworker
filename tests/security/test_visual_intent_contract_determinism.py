import ast
import inspect

import app.capabilities.intent_contract as intent_contract_module
from app.capabilities.intent_contract import build_visual_intent_contract


def test_visual_intent_contract_is_deterministic() -> None:
    text = "Tạo ảnh để đăng Facebook, xong gửi lại đây, không gửi trùng."
    results = [build_visual_intent_contract(text) for _ in range(100)]
    assert all(result == results[0] for result in results)


def test_visual_intent_contract_imports_no_io_model_or_policy_modules() -> None:
    source = inspect.getsource(intent_contract_module)
    tree = ast.parse(source)
    imported_roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".", maxsplit=1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".", maxsplit=1)[0])

    forbidden = {
        "anthropic",
        "asyncio",
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
        "app.policy",
    }
    assert imported_roots.isdisjoint(forbidden)
