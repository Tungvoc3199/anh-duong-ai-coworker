from __future__ import annotations

from typing import Any

import pytest

from app.capabilities import CapabilityDecision, CapabilityKind, CapabilityRouter
from app.context_builder import ContextBuilder, ContextSectionKind
from app.memory import HybridMemorySearchResult, MemoryRepositoryError
from app.routing import FastRoute, FastRouter
from tests.unit.test_context_builder import (
    RecordingRetriever,
    _build_request,
    _memory,
)


class FailingRetriever:
    def retrieve(
        self,
        query: str,
        **kwargs: Any,
    ) -> list[HybridMemorySearchResult]:
        raise MemoryRepositoryError("database temporarily unavailable")


def test_repeated_builds_are_equal_and_do_not_mutate_inputs() -> None:
    result = _memory()
    retriever = RecordingRetriever([result])
    request = _build_request()
    request_before = request.model_dump(mode="json")

    first = ContextBuilder(retriever).build(request)
    second = ContextBuilder(retriever).build(request)

    assert first == second
    assert request.model_dump(mode="json") == request_before
    assert retriever.results == [result]


def test_empty_optional_context_and_memory_still_builds_all_markers() -> None:
    request = _build_request().model_copy(
        update={
            "project_context": None,
            "task_context": None,
            "memory_scope_id": None,
        }
    )

    bundle = ContextBuilder(RecordingRetriever([])).build(request)

    project = next(
        section
        for section in bundle.sections
        if section.kind is ContextSectionKind.PROJECT_CONTEXT
    )
    task = next(
        section
        for section in bundle.sections
        if section.kind is ContextSectionKind.ACTIVE_TASK
    )
    memory = next(
        section
        for section in bundle.sections
        if section.kind is ContextSectionKind.RELEVANT_MEMORY
    )
    assert project.content == "none"
    assert task.content == "none"
    assert memory.content == "none"
    assert bundle.warnings == ()


def test_recoverable_memory_failure_keeps_required_context_and_warns() -> None:
    bundle = ContextBuilder(FailingRetriever()).build(_build_request())

    assert "[PERSONA]" in bundle.rendered_context
    assert "[ROUTING_DECISIONS]" in bundle.rendered_context
    assert "[CURRENT_REQUEST]" in bundle.rendered_context
    assert "Triển khai Context Builder v1" in bundle.rendered_context
    assert bundle.warnings == (
        "memory_retrieval_failed: MemoryRepositoryError",
    )
    memory = next(
        section
        for section in bundle.sections
        if section.kind is ContextSectionKind.RELEVANT_MEMORY
    )
    assert memory.content == "none"


def test_duplicate_memory_is_dropped_and_equal_scores_use_memory_id_order() -> None:
    duplicate = _memory("mem_a", content="Nội dung trùng", score=0.5)
    results = [
        _memory("mem_b", content="Nội dung B", score=0.5),
        duplicate,
        duplicate,
    ]

    bundle = ContextBuilder(RecordingRetriever(results)).build(_build_request())

    memory = next(
        section
        for section in bundle.sections
        if section.kind is ContextSectionKind.RELEVANT_MEMORY
    )
    assert memory.content.index("mem_a") < memory.content.index("mem_b")
    assert memory.content.count("id: mem_a") == 1
    assert tuple(item.source_ref for item in bundle.dropped_items) == (
        "memory:mem_a",
    )
    assert bundle.dropped_items[0].reason == "duplicate_memory"


def test_vietnamese_content_is_preserved_while_secret_value_is_redacted() -> None:
    secret = "sk-proj-abcdefghijklmnopqrstuvwxyz"
    request = _build_request().model_copy(
        update={
            "current_request": f"Ghi nhớ tiếng Việt; api_key={secret}",
        }
    )

    bundle = ContextBuilder(RecordingRetriever([])).build(request)

    assert "Ghi nhớ tiếng Việt" in bundle.rendered_context
    assert secret not in bundle.rendered_context
    assert "api_key=[REDACTED]" in bundle.rendered_context


def test_explicit_no_capability_is_rendered_without_router_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_router_call(*args: object, **kwargs: object) -> None:
        raise AssertionError("Context Builder must not run a router")

    monkeypatch.setattr(FastRouter, "route", unexpected_router_call)
    monkeypatch.setattr(CapabilityRouter, "route", unexpected_router_call)
    request = _build_request().model_copy(
        update={
            "capability_decision": CapabilityDecision(
                capability=CapabilityKind.UNKNOWN_WORKFLOW,
                source_route=FastRoute.WORKFLOW,
                reason_code="workflow.unknown",
                matched_signals=(),
            )
        }
    )

    bundle = ContextBuilder(RecordingRetriever([])).build(request)

    assert "selected_capability: unknown_workflow" in bundle.rendered_context

