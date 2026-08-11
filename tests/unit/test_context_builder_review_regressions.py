from __future__ import annotations

from dataclasses import replace

from app.context_builder import ContextBuilder, ContextSectionKind
from tests.unit.test_context_builder import (
    RecordingRetriever,
    _build_request,
    _memory,
)
from tests.unit.test_context_builder_budget import (
    CharacterTokenEstimator,
    _budget,
    _small_persona,
)


def test_secret_values_are_redacted_from_provenance_and_change_metadata() -> None:
    secret = "sk-proj-abcdefghijklmnopqrstuvwxyz"
    result = _memory("mem_secret", source=f"api_key={secret}")

    bundle = ContextBuilder(RecordingRetriever([result])).build(
        _build_request()
    )

    serialized_bundle = str(bundle.model_dump(mode="json"))
    assert secret not in serialized_bundle
    memory_provenance = next(
        item
        for item in bundle.provenance
        if item.section is ContextSectionKind.RELEVANT_MEMORY
    )
    assert "memory-source:api_key=[REDACTED]" in memory_provenance.source_refs


def test_fully_dropped_memory_is_not_reported_as_truncated() -> None:
    result = _memory("mem_oversized_metadata", content="short", score=0.9)
    result = replace(
        result,
        memory=result.memory.model_copy(
            update={
                "title": "T" * 1_000,
                "source": "S" * 1_000,
            }
        ),
    )
    request = _build_request().model_copy(
        update={
            "persona": _small_persona(),
            "project_context": None,
            "task_context": None,
            "token_budget": _budget(650),
        }
    )

    bundle = ContextBuilder(
        RecordingRetriever([result]),
        CharacterTokenEstimator(),
    ).build(request)

    memory = next(
        section
        for section in bundle.sections
        if section.kind is ContextSectionKind.RELEVANT_MEMORY
    )
    assert memory.content == "none"
    assert memory.truncated is False
    assert bundle.truncated_items == ()
    assert any(
        item.source_ref == "memory:mem_oversized_metadata"
        and item.reason == "memory_budget"
        for item in bundle.dropped_items
    )

