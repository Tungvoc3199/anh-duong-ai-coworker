import ast
import inspect

import app.policy.engine as policy_engine_module
from app.policy.engine import PolicyEngine
from app.policy.models import PolicyAction
from app.policy.path_scope import WorkspacePathPolicy


def test_policy_engine_imports_no_llm_network_or_shell_modules(
    tmp_path,
) -> None:
    source = inspect.getsource(policy_engine_module)
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
        "httpx",
        "openai",
        "requests",
        "socket",
        "subprocess",
    }
    assert imported_roots.isdisjoint(forbidden_modules)

    engine = PolicyEngine(WorkspacePathPolicy((tmp_path,)))
    action = PolicyAction(name="restart_service")
    assert engine.evaluate(action) == engine.evaluate(action)
