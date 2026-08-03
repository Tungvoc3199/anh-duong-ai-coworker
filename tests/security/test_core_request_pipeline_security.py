from __future__ import annotations

import ast
import inspect
from pathlib import Path

from app.orchestration import CoreRequestPipeline


def test_pipeline_constructor_has_no_execution_or_queue_dependency() -> None:
    parameters = set(inspect.signature(CoreRequestPipeline).parameters)

    assert parameters.isdisjoint(
        {
            "async_task_service",
            "enqueue",
            "executor",
            "notifier",
            "openclaw",
            "policy_engine",
            "telegram",
        }
    )


def test_orchestration_import_boundary_excludes_external_execution_modules() -> None:
    imported_modules: set[str] = set()
    for path in Path("app/orchestration").glob("*.py"):
        syntax_tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(syntax_tree):
            if isinstance(node, ast.Import):
                imported_modules.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_modules.add(node.module)

    forbidden_fragments = {
        "9router",
        "anthropic",
        "app.async_tasks",
        "app.openclaw",
        "httpx",
        "openai",
        "requests",
        "socket",
        "subprocess",
        "telegram",
    }
    assert not any(
        fragment in imported
        for imported in imported_modules
        for fragment in forbidden_fragments
    )
