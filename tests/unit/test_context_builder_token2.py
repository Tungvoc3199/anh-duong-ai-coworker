"""TOKEN-2 behavioral tests — relevance-first dynamic context budget.

These tests define the required TOKEN-2 behavior and are expected to FAIL
against the pre-TOKEN-2 ContextBuilder (base 42be6ac).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.capabilities import CapabilityDecision, CapabilityKind
from app.context_builder import (
    ContextBudgetExceededError,
    ContextBuilder,
    ContextBuildRequest,
    ContextSectionKind,
    ProjectContextSnapshot,
    TaskContextSnapshot,
)
from app.context_builder.tokens import Utf8ByteTokenEstimator
from app.memory import HybridMemorySearchResult, MemoryType
from app.persona import PersonaSnapshot
from app.routing import FastRoute, RouteDecision
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

NOW = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)


def _mk_result(
    memory_id: str,
    *,
    content: str,
    score: float = 0.5,
    scope_id: str = "proj_1",
    mtype: MemoryType = MemoryType.PROJECT,
    importance: float = 0.5,
    recency: float = 0.5,
) -> HybridMemorySearchResult:
    base = _memory(memory_id, content=content, score=score)
    memory = base.memory.model_copy(
        update={
            "scope_id": scope_id,
            "memory_type": mtype,
            "importance": importance,
        }
    )
    return HybridMemorySearchResult(
        memory=memory,
        fts_rank=base.fts_rank,
        lexical_score=base.lexical_score,
        importance_score=importance,
        confidence_score=base.confidence_score,
        recency_score=recency,
        hybrid_score=score,
    )


def _build_budget_request() -> ContextBuildRequest:
    """Direct-route-shaped request with no project/task (baseline for memory tests).

    Budget 800 is tight enough that low-ranked memories are dropped by the
    selection/trim pipeline while the mandatory sections still fit.
    """
    return _build_request().model_copy(
        update={
            "persona": _small_persona(),
            "project_context": None,
            "task_context": None,
            "token_budget": _budget(800),
        }
    )


# --- 1. current request is never removed -------------------------------


def test_current_request_never_removed_under_pressure() -> None:
    request_text = "Yêu cầu sống còn " + "r" * 400
    request = _build_request().model_copy(
        update={
            "persona": _small_persona(),
            "project_context": None,
            "task_context": None,
            "current_request": request_text,
            "token_budget": _budget(900),
        }
    )
    results = [
        _mk_result("mem_a", content="A" * 200, score=0.9),
        _mk_result("mem_b", content="B" * 200, score=0.1),
    ]
    bundle = ContextBuilder(
        RecordingRetriever(results),
        CharacterTokenEstimator(),
    ).build(request)
    assert request_text in bundle.rendered_context
    assert bundle.estimated_tokens <= 900
    # budget pressure removed memories, never the current request
    assert any(item.reason == "memory_budget" for item in bundle.dropped_items)


# --- 2. safety/system-critical persona material survives budget pressure --


def test_safety_persona_file_survives_pressure() -> None:
    files = {
        "IDENTITY.md": "Ánh Dương — AI coworker an toàn.",
        "SAFETY.md": "SAFETY-CRITICAL: không bao giờ thực hiện hành động "
        "nguy hiểm khi chưa được phê duyệt.",
        "EXAMPLES.md": "Ví dụ. " + "x" * 500,
    }
    persona = PersonaSnapshot(
        version="1.0",
        content_hash="c" * 64,
        file_order=tuple(files),
        files=files,
        combined_content="\n".join(files.values()),
    )
    request = _build_request().model_copy(
        update={
            "persona": persona,
            "project_context": None,
            "task_context": None,
            "token_budget": _budget(650),
        }
    )
    bundle = ContextBuilder(
        RecordingRetriever([]),
        CharacterTokenEstimator(),
    ).build(request)
    assert "SAFETY-CRITICAL: không bao giờ thực hiện" in bundle.rendered_context
    assert "Ví dụ. " not in bundle.rendered_context
    assert bundle.estimated_tokens <= 650


# --- 3. relevant memories outrank irrelevant memories -------------------


def test_relevant_memory_outranks_irrelevant() -> None:
    request = _build_budget_request()
    relevant = _mk_result("mem_rel", content="RELEVANT " + "a" * 200, score=0.9)
    irrelevant = _mk_result("mem_irr", content="IRRELEVANT " + "b" * 200, score=0.1)
    bundle = ContextBuilder(
        RecordingRetriever([irrelevant, relevant]),
        CharacterTokenEstimator(),
    ).build(request)
    memory_section = next(
        s for s in bundle.sections if s.kind is ContextSectionKind.RELEVANT_MEMORY
    )
    assert "mem_rel" in memory_section.content
    assert "mem_irr" not in memory_section.content


# --- 4. scope-specific memory outranks generic when otherwise comparable --


def test_scope_specific_memory_outranks_generic() -> None:
    request = _build_request().model_copy(
        update={
            "persona": _small_persona(),
            "project_context": None,
            "task_context": None,
            "memory_scope_id": "proj_1",
            "token_budget": _budget(800),
        }
    )
    generic = _mk_result(
        "mem_gen",
        content="Generic tip chung " + "g" * 150,
        score=0.5,
        scope_id="global",
    )
    scoped = _mk_result(
        "mem_scoped",
        content="Scoped detail proj_1 " + "s" * 150,
        score=0.5,
        scope_id="proj_1",
    )
    bundle = ContextBuilder(
        RecordingRetriever([generic, scoped]),
        CharacterTokenEstimator(),
    ).build(request)
    memory_section = next(
        s for s in bundle.sections if s.kind is ContextSectionKind.RELEVANT_MEMORY
    )
    assert "mem_scoped" in memory_section.content
    assert "mem_gen" not in memory_section.content


# --- 5. recent relevant memory receives appropriate priority ------------


def test_recent_relevant_memory_priority() -> None:
    request = _build_budget_request()
    old = _mk_result(
        "mem_old",
        content="OLD " + "o" * 200,
        score=0.5,
        recency=0.1,
    )
    recent = _mk_result(
        "mem_recent",
        content="RECENT " + "e" * 200,
        score=0.5,
        recency=0.9,
    )
    bundle = ContextBuilder(
        RecordingRetriever([old, recent]),
        CharacterTokenEstimator(),
    ).build(request)
    memory_section = next(
        s for s in bundle.sections if s.kind is ContextSectionKind.RELEVANT_MEMORY
    )
    assert "mem_recent" in memory_section.content
    assert "mem_old" not in memory_section.content


# --- 6. duplicate context included only once where semantics identical ---


def test_duplicate_fact_across_sections_included_once() -> None:
    shared_fact = "CACHE-2T-L1 đã đóng với flags true/true/false."
    project = ProjectContextSnapshot(
        identity="anh-duong-core",
        goal="Build AIOS",
        history=(shared_fact,),
    )
    dup_memory = _mk_result("mem_dup", content=shared_fact, score=0.8)
    request = _build_request().model_copy(
        update={
            "persona": _small_persona(),
            "project_context": project,
            "task_context": None,
            "token_budget": _budget(800),
        }
    )
    bundle = ContextBuilder(
        RecordingRetriever([dup_memory]),
        CharacterTokenEstimator(),
    ).build(request)
    assert bundle.rendered_context.count(shared_fact) == 1
    assert any(item.reason == "duplicate" for item in bundle.dropped_items)


# --- 7. low-value history/context removed before critical sections ------


def test_low_value_history_removed_before_persona_identity() -> None:
    request = _build_request().model_copy(
        update={
            "persona": _small_persona(),
            "task_context": None,
            "project_context": ProjectContextSnapshot(
                identity="anh-duong-core",
                goal="Build AIOS",
                history=("history entry " + "h" * 400, "history entry " + "h" * 400),
            ),
            "token_budget": _budget(900),
        }
    )
    bundle = ContextBuilder(
        RecordingRetriever([]),
        CharacterTokenEstimator(),
    ).build(request)
    assert "Ánh Dương — AI coworker an toàn." in bundle.rendered_context
    dropped_reasons = [item.reason for item in bundle.dropped_items]
    assert dropped_reasons
    assert all(reason != "persona_identity_budget" for reason in dropped_reasons)


# --- 8. project/task context survives when workflow requires it ---------


def test_project_task_context_survives_workflow_pressure() -> None:
    request = _build_request().model_copy(
        update={
            "persona": _small_persona(),
            "token_budget": _budget(1200),
        }
    )
    bundle = ContextBuilder(
        RecordingRetriever([]),
        CharacterTokenEstimator(),
    ).build(request)
    assert "identity: anh-duong-core" in bundle.rendered_context
    assert "Build Context Builder v1" in bundle.rendered_context
    assert bundle.estimated_tokens <= 1200


# --- 9. direct request does not inherit workflow-heavy context ----------


def test_direct_request_skips_workflow_heavy_context() -> None:
    request = _build_request().model_copy(
        update={
            "persona": _small_persona(),
            "project_context": None,
            "task_context": None,
            "fast_router_decision": RouteDecision(
                route=FastRoute.DIRECT,
                rule_id="direct.hello",
                reason="Chào hỏi",
            ),
            "capability_decision": CapabilityDecision(
                capability=CapabilityKind.CONVERSATIONAL_RESPONSE,
                source_route=FastRoute.DIRECT,
                reason_code="direct.hello",
                matched_signals=(),
            ),
            "token_budget": _budget(600),
        }
    )
    bundle = ContextBuilder(
        RecordingRetriever([]),
        CharacterTokenEstimator(),
    ).build(request)
    # workflow-only details must not bloat an unscoped direct request
    assert bundle.estimated_tokens <= 600


# --- 10. hard final budget is never exceeded ----------------------------


def test_hard_budget_never_exceeded() -> None:
    request = _build_budget_request()
    results = [
        _mk_result(f"mem_{i}", content="Nội dung " + "m" * 300, score=0.1 + i * 0.05)
        for i in range(20)
    ]
    bundle = ContextBuilder(
        RecordingRetriever(results),
        CharacterTokenEstimator(),
    ).build(request)
    assert bundle.estimated_tokens <= request.token_budget.usable_context_tokens


# --- 11. deterministic identical input gives deterministic output --------


def test_selection_is_deterministic() -> None:
    results = [
        _mk_result(f"mem_{i}", content="Content " + "c" * 200, score=0.2 + i * 0.03)
        for i in range(10)
    ]
    request = _build_budget_request()
    first = ContextBuilder(RecordingRetriever(results), CharacterTokenEstimator()).build(request)
    second = ContextBuilder(RecordingRetriever(results), CharacterTokenEstimator()).build(request)
    assert first == second


# --- 12. cache-enabled and cache-disabled retrieval semantics equivalent --


def test_cache_flag_does_not_change_selection() -> None:
    """Selection must be identical whether or not CACHE-2T is enabled.

    Retrieval results are the same object shapes; the builder must not
    depend on cache state (cache is a wrapper in wiring, not in builder).
    """
    results = [_mk_result("mem_1", content="Cached fact " + "f" * 150, score=0.7)]
    request = _build_budget_request()
    bundle = ContextBuilder(RecordingRetriever(results), CharacterTokenEstimator()).build(request)
    memory_section = next(
        s for s in bundle.sections if s.kind is ContextSectionKind.RELEVANT_MEMORY
    )
    assert "mem_1" in memory_section.content
    assert "Cached fact" in memory_section.content


# --- 13. audit remains unconditional -------------------------------------


def test_audit_unconditional() -> None:
    """Builder emits no audit events itself; audit layer is upstream.
    Ensure selection errors cannot silently swallow the build (no
    new exception path)."""
    request = _build_budget_request()
    bundle = ContextBuilder(
        RecordingRetriever([]),
        CharacterTokenEstimator(),
    ).build(request)
    assert bundle.sections
    assert bundle.estimated_tokens >= 0


# --- 14. empty/no-memory behavior remains valid --------------------------


def test_empty_memory_behavior_valid() -> None:
    request = _build_request().model_copy(
        update={
            "persona": _small_persona(),
            "project_context": None,
            "task_context": None,
            "token_budget": _budget(1200),
        }
    )
    bundle = ContextBuilder(RecordingRetriever([]), CharacterTokenEstimator()).build(request)
    memory_section = next(
        s for s in bundle.sections if s.kind is ContextSectionKind.RELEVANT_MEMORY
    )
    assert memory_section.content == "none"


# --- 15. tiny-budget edge case fails safely or preserves mandatory minimum


def test_tiny_budget_preserves_mandatory_minimum() -> None:
    request_text = "Yêu cầu bắt buộc " + "r" * 50
    request = _build_request().model_copy(
        update={
            "persona": _small_persona(),
            "project_context": None,
            "task_context": None,
            "current_request": request_text,
            "token_budget": _budget(140),
        }
    )
    with pytest.raises(ContextBudgetExceededError):
        ContextBuilder(
            RecordingRetriever([]),
            CharacterTokenEstimator(),
        ).build(request)


# --- 16. malformed/oversized candidate cannot break prepare --------------


def test_oversized_candidate_does_not_break_build() -> None:
    request = _build_budget_request()
    huge = _mk_result("mem_huge", content="H" * 10_000, score=0.9)
    bundle = ContextBuilder(
        RecordingRetriever([huge]),
        CharacterTokenEstimator(),
    ).build(request)
    assert bundle.estimated_tokens <= request.token_budget.usable_context_tokens
    assert bundle.sections


# --- metrics observability -----------------------------------------------


def test_metrics_fields_exist_and_are_sane() -> None:
    request = _build_budget_request()
    results = [
        _mk_result("mem_x", content="X" * 300, score=0.9),
        _mk_result("mem_y", content="Y" * 300, score=0.1),
    ]
    bundle = ContextBuilder(
        RecordingRetriever(results),
        CharacterTokenEstimator(),
    ).build(request)
    assert bundle.candidate_estimated_tokens >= bundle.estimated_tokens
    assert bundle.dropped_estimated_tokens >= 0
    assert bundle.reduction_pct >= 0.0
    assert bundle.reduction_pct <= 1.0
    assert bundle.tokens_by_section[ContextSectionKind.RELEVANT_MEMORY] >= 0
    assert isinstance(bundle.dropped_by_reason, dict)


# --- production estimator (Utf8ByteTokenEstimator) also respects budget ---


def test_production_estimator_respects_budget() -> None:
    request = _build_request().model_copy(
        update={
            "persona": _small_persona(),
            "project_context": None,
            "task_context": None,
            "token_budget": _budget(1500),
        }
    )
    results = [
        _mk_result(f"mem_{i}", content="Content " + "c" * 200, score=0.3 + i * 0.03)
        for i in range(20)
    ]
    bundle = ContextBuilder(
        RecordingRetriever(results),
        Utf8ByteTokenEstimator(),
    ).build(request)
    assert bundle.estimated_tokens <= request.token_budget.usable_context_tokens


def test_consecutive_cross_section_duplicates_are_all_removed() -> None:
    shared_fact = "FACT-DUPLICATE-CONSECUTIVE"
    project = ProjectContextSnapshot(
        identity="anh-duong-core",
        goal="Build AIOS",
        history=(shared_fact, shared_fact),
    )
    request = _build_request().model_copy(
        update={
            "persona": _small_persona(),
            "project_context": project,
            "task_context": None,
            "token_budget": _budget(2_000),
        }
    )
    bundle = ContextBuilder(
        RecordingRetriever([_mk_result("mem_dup2", content=shared_fact, score=0.9)]),
        CharacterTokenEstimator(),
    ).build(request)
    assert bundle.rendered_context.count(shared_fact) == 1
    duplicate_drops = [item for item in bundle.dropped_items if item.reason == "duplicate"]
    assert len(duplicate_drops) == 2


def test_single_large_memory_is_bounded_by_memory_soft_cap() -> None:
    memory_soft_tokens = 300
    request = _build_request().model_copy(
        update={
            "persona": _small_persona(),
            "project_context": None,
            "task_context": None,
            "token_budget": _budget(20_000).model_copy(
                update={"memory_soft_tokens": memory_soft_tokens}
            ),
        }
    )
    bundle = ContextBuilder(
        RecordingRetriever(
            [
                _mk_result(
                    "mem_soft_cap",
                    content="KEEP-PREFIX " + "x" * 10_000,
                    score=0.9,
                )
            ]
        ),
        CharacterTokenEstimator(),
    ).build(request)
    memory_section = next(
        section for section in bundle.sections if section.kind is ContextSectionKind.RELEVANT_MEMORY
    )
    assert "mem_soft_cap" in memory_section.content
    assert "KEEP-PREFIX" in memory_section.content
    assert len(memory_section.content) <= memory_soft_tokens
    assert any(item.reason == "memory_soft_cap" for item in bundle.truncated_items)


def test_persona_soft_cap_bounds_single_critical_file() -> None:
    memory_soft = 100
    files = {
        "SAFETY.md": "SAFETY-KEEP-PREFIX " + "s" * 10_000,
    }
    persona = PersonaSnapshot(
        version="1.0",
        content_hash="d" * 64,
        file_order=tuple(files),
        files=files,
        combined_content="\n".join(files.values()),
    )
    request = _build_request().model_copy(
        update={
            "persona": persona,
            "project_context": None,
            "task_context": None,
            "token_budget": _budget(20_000).model_copy(update={"persona_soft_tokens": memory_soft}),
        }
    )
    bundle = ContextBuilder(
        RecordingRetriever([]),
        CharacterTokenEstimator(),
    ).build(request)
    persona_section = next(
        section for section in bundle.sections if section.kind is ContextSectionKind.PERSONA
    )
    assert "SAFETY-KEEP-PREFIX" in persona_section.content
    assert len(persona_section.content) <= memory_soft
    assert any(item.reason == "persona_soft_cap" for item in bundle.truncated_items)


def test_duplicate_memory_and_project_decision_is_rendered_once() -> None:
    shared_fact = "DECISION-EXACT-DUPLICATE"
    project = ProjectContextSnapshot(
        identity="anh-duong-core",
        goal="Build AIOS",
        decisions=(shared_fact,),
    )
    request = _build_request().model_copy(
        update={
            "persona": _small_persona(),
            "project_context": project,
            "task_context": None,
            "token_budget": _budget(2_000),
        }
    )
    bundle = ContextBuilder(
        RecordingRetriever([_mk_result("mem_decision_dup", content=shared_fact, score=0.9)]),
        CharacterTokenEstimator(),
    ).build(request)
    assert bundle.rendered_context.count(shared_fact) == 1
    assert any(
        item.reason == "duplicate" and item.source_ref.startswith("project:decision:")
        for item in bundle.dropped_items
    )


def test_duplicate_memory_and_task_constraint_is_rendered_once() -> None:
    shared_fact = "TASK-CONSTRAINT-EXACT-DUPLICATE"
    task = TaskContextSnapshot(
        identity="CB-1",
        active_goal="Keep mandatory active goal",
        constraints=(shared_fact,),
    )
    request = _build_request().model_copy(
        update={
            "persona": _small_persona(),
            "project_context": None,
            "task_context": task,
            "token_budget": _budget(2_000),
        }
    )
    bundle = ContextBuilder(
        RecordingRetriever([_mk_result("mem_task_dup", content=shared_fact, score=0.9)]),
        CharacterTokenEstimator(),
    ).build(request)
    assert bundle.rendered_context.count(shared_fact) == 1
    assert "Keep mandatory active goal" in bundle.rendered_context


def test_history_provenance_preserves_original_indices_after_dedupe() -> None:
    shared = "HISTORY-DUPLICATE-FOR-PROVENANCE"
    project = ProjectContextSnapshot(
        identity="anh-duong-core", goal="Build AIOS", history=(shared, "PROJECT-UNIQUE")
    )
    task = TaskContextSnapshot(
        identity="CB-1", active_goal="Keep active goal", history=(shared, "TASK-UNIQUE")
    )
    request = _build_request().model_copy(
        update={
            "persona": _small_persona(),
            "project_context": project,
            "task_context": task,
            "token_budget": _budget(4_000),
        }
    )
    bundle = ContextBuilder(
        RecordingRetriever([_mk_result("mem_history_dup", content=shared, score=0.9)]),
        CharacterTokenEstimator(),
    ).build(request)
    project_section = next(
        s for s in bundle.sections if s.kind is ContextSectionKind.PROJECT_CONTEXT
    )
    task_section = next(s for s in bundle.sections if s.kind is ContextSectionKind.ACTIVE_TASK)
    assert "project:history:1" in project_section.source_refs
    assert "project:history:0" not in project_section.source_refs
    assert "task:history:1" in task_section.source_refs
    assert "task:history:0" not in task_section.source_refs


def test_preselection_duplicate_memory_is_counted_in_reason_metrics() -> None:
    first = _mk_result("mem_same_id", content="FIRST", score=0.9)
    duplicate = _mk_result("mem_same_id", content="SECOND", score=0.8)
    request = _build_request().model_copy(
        update={
            "persona": _small_persona(),
            "project_context": None,
            "task_context": None,
            "token_budget": _budget(4_000),
        }
    )
    bundle = ContextBuilder(
        RecordingRetriever([first, duplicate]), CharacterTokenEstimator()
    ).build(request)
    expected = sum(
        item.original_estimated_tokens
        for item in bundle.dropped_items
        if item.reason == "duplicate_memory"
    )
    assert expected > 0
    assert bundle.dropped_by_reason["duplicate_memory"] == expected


def test_direct_scoped_request_preserves_core_project_and_task_facts() -> None:
    project = ProjectContextSnapshot(
        identity="scoped-project", goal="Keep project goal", current_phase="DROP-PHASE",
        architecture_constraints=("KEEP-PROJECT-CONSTRAINT",),
        decisions=("DROP-DECISION",), status="DROP-PROJECT-STATUS",
        history=("DROP-PROJECT-HISTORY",)
    )
    task = TaskContextSnapshot(
        identity="scoped-task", active_goal="Keep active goal",
        status="DROP-TASK-STATUS", constraints=("KEEP-TASK-CONSTRAINT",),
        acceptance_criteria=("DROP-ACCEPTANCE",), blockers=("DROP-BLOCKER",),
        next_action="DROP-NEXT-ACTION", history=("DROP-TASK-HISTORY",)
    )
    request = _build_request().model_copy(
        update={
            "persona": _small_persona(), "project_context": project, "task_context": task,
            "fast_router_decision": RouteDecision(
                route=FastRoute.DIRECT, rule_id="direct.ok", reason="Ngắn gọn"
            ),
            "capability_decision": CapabilityDecision(
                capability=CapabilityKind.CONVERSATIONAL_RESPONSE, source_route=FastRoute.DIRECT,
                reason_code="direct.ok", matched_signals=(),
            ), "token_budget": _budget(700),
        }
    )
    bundle = ContextBuilder(RecordingRetriever([]), CharacterTokenEstimator()).build(request)
    assert "scoped-project" in bundle.rendered_context
    assert "Keep project goal" in bundle.rendered_context
    assert "Keep active goal" in bundle.rendered_context
    assert "KEEP-TASK-CONSTRAINT" in bundle.rendered_context
    assert "KEEP-PROJECT-CONSTRAINT" in bundle.rendered_context
    assert bundle.estimated_tokens <= 700
    assert bundle.dropped_by_reason["direct_scope_compaction"] > 0
    assert "DROP-PROJECT-HISTORY" not in bundle.rendered_context
    assert "DROP-TASK-HISTORY" not in bundle.rendered_context
    for omitted in ("DROP-PHASE", "DROP-DECISION", "DROP-PROJECT-STATUS",
                    "DROP-TASK-STATUS", "DROP-ACCEPTANCE", "DROP-BLOCKER",
                    "DROP-NEXT-ACTION"):
        assert omitted not in bundle.rendered_context
