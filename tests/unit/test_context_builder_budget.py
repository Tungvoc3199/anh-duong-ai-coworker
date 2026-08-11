from __future__ import annotations

import pytest

from app.context_builder import (
    ContextBudgetExceededError,
    ContextBuilder,
    ContextSectionKind,
    ContextTokenBudget,
    ProjectContextSnapshot,
    TaskContextSnapshot,
)
from app.persona import PersonaSnapshot
from tests.unit.test_context_builder import (
    RecordingRetriever,
    _build_request,
    _memory,
)


class CharacterTokenEstimator:
    def estimate(self, text: str) -> int:
        return len(text)


def _budget(usable_tokens: int, *, task_soft_tokens: int = 3_200) -> ContextTokenBudget:
    return ContextTokenBudget(
        context_window_tokens=usable_tokens,
        response_reserve_tokens=0,
        runtime_reserve_tokens=0,
        task_soft_tokens=task_soft_tokens,
    )


def _small_persona(*, include_examples: bool = False) -> PersonaSnapshot:
    files = {"IDENTITY.md": "Ánh Dương — AI coworker an toàn."}
    if include_examples:
        files["EXAMPLES.md"] = "Ví dụ phụ. " + "x" * 800
    return PersonaSnapshot(
        version="1.0",
        content_hash="b" * 64,
        file_order=tuple(files),
        files=files,
        combined_content="\n".join(files.values()),
    )


def test_unused_soft_allocations_are_available_to_large_active_task() -> None:
    active_goal = "Hoàn thành active goal dài. " + "g" * 600
    request = _build_request().model_copy(
        update={
            "persona": _small_persona(),
            "project_context": None,
            "task_context": TaskContextSnapshot(
                identity="CB-1",
                active_goal=active_goal,
                constraints=("Không gọi LLM",),
            ),
            "token_budget": _budget(1_600, task_soft_tokens=10),
        }
    )

    bundle = ContextBuilder(
        RecordingRetriever([]),
        CharacterTokenEstimator(),
    ).build(request)

    assert active_goal in bundle.rendered_context
    task = next(
        section
        for section in bundle.sections
        if section.kind is ContextSectionKind.ACTIVE_TASK
    )
    assert task.estimated_tokens > request.token_budget.task_soft_tokens
    assert bundle.estimated_tokens <= 1_600


def test_low_relevance_memory_is_dropped_before_long_top_memory_is_truncated() -> None:
    request = _build_request().model_copy(
        update={
            "persona": _small_persona(),
            "project_context": None,
            "task_context": None,
            "token_budget": _budget(720),
        }
    )
    high = _memory("mem_high", content="HIGH " + "h" * 600, score=0.9)
    low = _memory("mem_low", content="LOW " + "l" * 600, score=0.1)

    bundle = ContextBuilder(
        RecordingRetriever([low, high]),
        CharacterTokenEstimator(),
    ).build(request)

    memory = next(
        section
        for section in bundle.sections
        if section.kind is ContextSectionKind.RELEVANT_MEMORY
    )
    assert "mem_low" not in memory.content
    assert "mem_high" in memory.content
    assert "source: memory-test" in memory.content
    assert memory.content.endswith("…")
    assert memory.truncated is True
    assert any(
        item.source_ref == "memory:mem_low"
        and item.reason == "memory_budget"
        for item in bundle.dropped_items
    )
    assert tuple(item.source_ref for item in bundle.truncated_items) == (
        "memory:mem_high",
    )
    assert bundle.truncated_items[0].reason == "memory_body_budget"
    assert (
        bundle.truncated_items[0].final_estimated_tokens
        < bundle.truncated_items[0].original_estimated_tokens
    )
    assert bundle.estimated_tokens <= bundle.token_budget.usable_context_tokens


def test_project_history_is_trimmed_before_task_history_and_core_fields_remain() -> None:
    project_old = "project-old-" + "p" * 300
    project_new = "project-new-" + "q" * 300
    task_old = "task-old-" + "t" * 300
    task_new = "task-new-" + "u" * 300
    request = _build_request().model_copy(
        update={
            "persona": _small_persona(),
            "project_context": ProjectContextSnapshot(
                identity="anh-duong-core",
                goal="Build AI coworker",
                architecture_constraints=("Không đổi schema",),
                history=(project_old, project_new),
            ),
            "task_context": TaskContextSnapshot(
                identity="CB-1",
                active_goal="Build Context Builder",
                status="implementing",
                constraints=("Không gọi LLM",),
                acceptance_criteria=("Current request luôn được giữ",),
                next_action="Run tests",
                history=(task_old, task_new),
            ),
            "token_budget": _budget(1_000),
        }
    )

    bundle = ContextBuilder(
        RecordingRetriever([]),
        CharacterTokenEstimator(),
    ).build(request)

    assert "Build AI coworker" in bundle.rendered_context
    assert "Không đổi schema" in bundle.rendered_context
    assert "Build Context Builder" in bundle.rendered_context
    assert "Không gọi LLM" in bundle.rendered_context
    assert "Current request luôn được giữ" in bundle.rendered_context
    history_changes = [
        item
        for item in bundle.dropped_items
        if "history_budget" in item.reason
    ]
    assert history_changes
    assert history_changes[0].source_ref == "project:history:0"
    if any(item.source_ref.startswith("task:history:") for item in history_changes):
        first_task_index = next(
            index
            for index, item in enumerate(history_changes)
            if item.source_ref.startswith("task:history:")
        )
        last_project_index = max(
            index
            for index, item in enumerate(history_changes)
            if item.source_ref.startswith("project:history:")
        )
        assert last_project_index < first_task_index
    assert bundle.estimated_tokens <= 1_000


def test_persona_examples_are_dropped_without_losing_identity_and_core_rule() -> None:
    request = _build_request().model_copy(
        update={
            "persona": _small_persona(include_examples=True),
            "project_context": None,
            "task_context": None,
            "token_budget": _budget(600),
        }
    )

    bundle = ContextBuilder(
        RecordingRetriever([]),
        CharacterTokenEstimator(),
    ).build(request)

    assert "Ánh Dương — AI coworker an toàn." in bundle.rendered_context
    assert "Ví dụ phụ" not in bundle.rendered_context
    assert any(
        item.source_ref == "persona-file:EXAMPLES.md"
        and item.reason == "persona_example_budget"
        for item in bundle.dropped_items
    )
    assert bundle.estimated_tokens <= 600


def test_required_content_overflow_raises_explicit_domain_error() -> None:
    current_request = "Yêu cầu bắt buộc " + "r" * 600
    request = _build_request().model_copy(
        update={
            "current_request": current_request,
            "persona": _small_persona(),
            "project_context": None,
            "task_context": None,
            "token_budget": _budget(100),
        }
    )

    with pytest.raises(ContextBudgetExceededError) as raised:
        ContextBuilder(
            RecordingRetriever([]),
            CharacterTokenEstimator(),
        ).build(request)

    assert raised.value.required_tokens > raised.value.usable_tokens
    assert raised.value.usable_tokens == 100

