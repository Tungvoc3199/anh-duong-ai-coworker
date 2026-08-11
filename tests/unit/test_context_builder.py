from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.capabilities import CapabilityDecision, CapabilityKind
from app.context_builder import (
    ContextBuilder,
    ContextBuildRequest,
    ContextSectionKind,
    ProjectContextSnapshot,
    TaskContextSnapshot,
)
from app.memory import HybridMemorySearchResult, Memory, MemoryType
from app.persona import PersonaSnapshot
from app.routing import FastRoute, RouteDecision


class RecordingRetriever:
    def __init__(self, results: list[HybridMemorySearchResult]) -> None:
        self.results = results
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def retrieve(self, query: str, **kwargs: Any) -> list[HybridMemorySearchResult]:
        self.calls.append((query, kwargs))
        return list(self.results)


def _persona() -> PersonaSnapshot:
    files = {
        "IDENTITY.md": "# Identity\n\nTôi là Ánh Dương.",
        "SOUL.md": "# Soul\n\nLuôn trung thực và an toàn.",
    }
    combined = "\n\n".join(files[name] for name in files)
    return PersonaSnapshot(
        version="1.0",
        language="vi",
        relationship="em-anh",
        tone="direct",
        content_hash="a" * 64,
        file_order=tuple(files),
        files=files,
        combined_content=combined,
    )


def _memory(
    memory_id: str = "mem_1",
    *,
    content: str = "Context Builder phải deterministic.",
    score: float = 0.9,
    source: str | None = "memory-test",
) -> HybridMemorySearchResult:
    now = datetime(2026, 7, 31, 12, 0, tzinfo=UTC)
    memory = Memory(
        id=memory_id,
        memory_type=MemoryType.PROJECT,
        scope_id="proj_1",
        title=f"Memory {memory_id}",
        content=content,
        summary=None,
        importance=0.8,
        confidence=0.9,
        source=source,
        expires_at=None,
        tags=("cb-1",),
        created_at=now,
        updated_at=now,
        version=1,
    )
    return HybridMemorySearchResult(
        memory=memory,
        fts_rank=-3.0,
        lexical_score=1.0,
        importance_score=0.8,
        confidence_score=0.9,
        recency_score=1.0,
        hybrid_score=score,
    )


def _build_request() -> ContextBuildRequest:
    return ContextBuildRequest(
        current_request="Triển khai Context Builder v1",
        persona=_persona(),
        fast_router_decision=RouteDecision(
            route=FastRoute.WORKFLOW,
            rule_id="workflow.action",
            reason="Yêu cầu triển khai code.",
        ),
        capability_decision=CapabilityDecision(
            capability=CapabilityKind.CODE_OPERATION,
            source_route=FastRoute.WORKFLOW,
            reason_code="workflow.code",
            matched_signals=("action:triển khai",),
        ),
        project_context=ProjectContextSnapshot(
            identity="anh-duong-core",
            goal="Build Ánh Dương AI Coworker",
            current_phase="CB-1",
            architecture_constraints=("Không đổi database schema",),
            decisions=("Dùng dependency injection",),
            status="FR-1 và CR-1 đã PASS",
        ),
        task_context=TaskContextSnapshot(
            identity="CB-1",
            active_goal="Build Context Builder v1",
            status="implementing",
            constraints=("Không gọi LLM",),
            acceptance_criteria=("Rendered context có sáu marker",),
            next_action="Viết test trước",
        ),
        memory_scope_id="proj_1",
    )


def test_builds_full_bundle_in_stable_section_order_with_one_retrieval() -> None:
    retriever = RecordingRetriever([_memory()])
    builder = ContextBuilder(retriever)

    bundle = builder.build(_build_request())

    assert tuple(section.kind for section in bundle.sections) == (
        ContextSectionKind.PERSONA,
        ContextSectionKind.ROUTING_DECISIONS,
        ContextSectionKind.PROJECT_CONTEXT,
        ContextSectionKind.ACTIVE_TASK,
        ContextSectionKind.RELEVANT_MEMORY,
        ContextSectionKind.CURRENT_REQUEST,
    )
    markers = (
        "[PERSONA]",
        "[ROUTING_DECISIONS]",
        "[PROJECT_CONTEXT]",
        "[ACTIVE_TASK]",
        "[RELEVANT_MEMORY]",
        "[CURRENT_REQUEST]",
    )
    positions = [bundle.rendered_context.index(marker) for marker in markers]
    assert positions == sorted(positions)
    assert "selected_route: workflow" in bundle.rendered_context
    assert "selected_capability: code_operation" in bundle.rendered_context
    assert "Context Builder phải deterministic." in bundle.rendered_context
    assert bundle.rendered_context.endswith("Triển khai Context Builder v1")
    assert bundle.estimated_tokens <= bundle.token_budget.usable_context_tokens
    assert bundle.remaining_tokens == (
        bundle.token_budget.usable_context_tokens - bundle.estimated_tokens
    )

    assert len(retriever.calls) == 1
    query, kwargs = retriever.calls[0]
    assert "Triển khai Context Builder v1" in query
    assert "Build Context Builder v1" in query
    assert "anh-duong-core" in query
    assert "workflow" in query
    assert "code_operation" in query
    assert kwargs == {"scope_id": "proj_1", "limit": 20}

    memory_provenance = next(
        item
        for item in bundle.provenance
        if item.section is ContextSectionKind.RELEVANT_MEMORY
    )
    assert "memory:mem_1" in memory_provenance.source_refs
    assert "memory-source:memory-test" in memory_provenance.source_refs

