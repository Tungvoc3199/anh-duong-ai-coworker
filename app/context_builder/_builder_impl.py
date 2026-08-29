from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Protocol, cast

from sqlalchemy.exc import SQLAlchemyError

from app.async_tasks.policy import (
    HARD_APPROVAL_GATED_STEPS,
    SAFE_STEPS_WITHOUT_APPROVAL,
    STEP_LEVEL_EXECUTION_CONSTRAINTS,
)
from app.audit.redaction import SecretRedactor
from app.capabilities import CapabilityKind
from app.context_builder.models import (
    ContextBudgetExceededError,
    ContextBuildRequest,
    ContextBundle,
    ContextItemChange,
    ContextProvenance,
    ContextSection,
    ContextSectionKind,
)
from app.context_builder.tokens import TokenEstimator, Utf8ByteTokenEstimator
from app.memory.repository import MemoryRepositoryError
from app.memory.retrieval import HybridMemorySearchResult
from app.routing import FastRoute

_SECTION_MARKERS: dict[ContextSectionKind, str] = {
    ContextSectionKind.PERSONA: "[PERSONA]",
    ContextSectionKind.ROUTING_DECISIONS: "[ROUTING_DECISIONS]",
    ContextSectionKind.PROJECT_CONTEXT: "[PROJECT_CONTEXT]",
    ContextSectionKind.ACTIVE_TASK: "[ACTIVE_TASK]",
    ContextSectionKind.RELEVANT_MEMORY: "[RELEVANT_MEMORY]",
    ContextSectionKind.CURRENT_REQUEST: "[CURRENT_REQUEST]",
}

_SECTION_PRIORITIES: dict[ContextSectionKind, int] = {
    ContextSectionKind.PERSONA: 90,
    ContextSectionKind.ROUTING_DECISIONS: 100,
    ContextSectionKind.PROJECT_CONTEXT: 60,
    ContextSectionKind.ACTIVE_TASK: 95,
    ContextSectionKind.RELEVANT_MEMORY: 40,
    ContextSectionKind.CURRENT_REQUEST: 100,
}


class HybridMemoryRetrieverProtocol(Protocol):
    def retrieve(
        self,
        query: str,
        *,
        scope_id: str | None = None,
        limit: int = 20,
    ) -> list[HybridMemorySearchResult]: ...


class ContextBuilder:
    """Build a deterministic context package without executing any action."""

    def __init__(
        self,
        retriever: HybridMemoryRetrieverProtocol,
        token_estimator: TokenEstimator | None = None,
        *,
        redactor: SecretRedactor | None = None,
        memory_limit: int = 20,
    ) -> None:
        self._retriever = retriever
        self._token_estimator = token_estimator or Utf8ByteTokenEstimator()
        self._redactor = redactor or SecretRedactor()
        self._memory_limit = memory_limit

    def build(self, request: ContextBuildRequest) -> ContextBundle:
        warnings: list[str] = []
        retrieved_memories = self._retrieve_memories(request, warnings)
        memories, dropped_items = self._prepare_memories(retrieved_memories)
        truncated_items: list[ContextItemChange] = []
        truncated_sections: set[ContextSectionKind] = set()
        memory_bodies: dict[str, str] = {}
        persona_files = list(request.persona.file_order)
        project_history = self._indexed_project_history(request)
        task_history = self._indexed_task_history(request)

        candidate_estimated_tokens = self._candidate_tokens(
            request,
            memories=memories,
            persona_files=persona_files,
            project_history=project_history,
            task_history=task_history,
            dropped_items=dropped_items,
        )
        dropped_by_reason: dict[str, int] = {}
        for change in dropped_items:
            dropped_by_reason[change.reason] = (
                dropped_by_reason.get(change.reason, 0) + change.original_estimated_tokens
            )

        if request.token_budget.selection_enabled:
            (
                request,
                memories,
                persona_files,
                project_history,
                task_history,
                selection_drops,
            ) = self._select_candidates(
                request,
                memories=memories,
                persona_files=persona_files,
                project_history=project_history,
                task_history=task_history,
            )
            for change in selection_drops:
                dropped_items.append(change)
                dropped_by_reason[change.reason] = (
                    dropped_by_reason.get(change.reason, 0) + change.original_estimated_tokens
                )

            memory_soft = request.token_budget.memory_soft_tokens
            if (
                memory_soft > 0
                and memories
                and self._memories_tokens(request, memories) > memory_soft
            ):
                memory = memories[0]
                original_body = memory.memory.summary or memory.memory.content
                original_tokens = self._token_estimator.estimate(
                    self._render_memory_block(memory, original_body)
                )
                low, high, best_body = 0, len(original_body), None
                while low <= high:
                    midpoint = (low + high) // 2
                    candidate = self._truncated_text(original_body, midpoint)
                    tokens = self._token_estimator.estimate(
                        self._render_memory_block(memory, candidate)
                    )
                    if tokens <= memory_soft:
                        best_body = candidate
                        low = midpoint + 1
                    else:
                        high = midpoint - 1
                if best_body is None:
                    removed = memories.pop()
                    change = self._dropped_memory_change(removed, "memory_soft_cap")
                    dropped_items.append(change)
                    dropped_by_reason[change.reason] = (
                        dropped_by_reason.get(change.reason, 0) + change.original_estimated_tokens
                    )
                else:
                    memory_bodies[memory.memory.id] = best_body
                    final_tokens = self._token_estimator.estimate(
                        self._render_memory_block(memory, best_body)
                    )
                    truncated_items.append(
                        ContextItemChange(
                            section=ContextSectionKind.RELEVANT_MEMORY,
                            source_ref=f"memory:{memory.memory.id}",
                            reason="memory_soft_cap",
                            original_estimated_tokens=original_tokens,
                            final_estimated_tokens=final_tokens,
                        )
                    )
                    truncated_sections.add(ContextSectionKind.RELEVANT_MEMORY)

            persona_soft = request.token_budget.persona_soft_tokens
            if persona_soft > 0 and self._persona_tokens(request, persona_files) > persona_soft:
                files = dict(request.persona.files)
                for filename in reversed(persona_files):
                    if self._persona_tokens(request, persona_files) <= persona_soft:
                        break
                    original = files.get(filename, "")
                    if not original:
                        continue
                    original_tokens = self._token_estimator.estimate(original)
                    low, high, best_body, best_request = 0, len(original), None, None
                    while low <= high:
                        midpoint = (low + high) // 2
                        candidate = self._truncated_text(original, midpoint)
                        candidate_files = {**files, filename: candidate}
                        candidate_persona = request.persona.model_copy(
                            update={"files": candidate_files}
                        )
                        candidate_request = request.model_copy(
                            update={"persona": candidate_persona}
                        )
                        if self._persona_tokens(candidate_request, persona_files) <= persona_soft:
                            best_body, best_request = candidate, candidate_request
                            low = midpoint + 1
                        else:
                            high = midpoint - 1
                    if best_request is not None and best_body is not None:
                        request = best_request
                        files[filename] = best_body
                        truncated_items.append(
                            ContextItemChange(
                                section=ContextSectionKind.PERSONA,
                                source_ref=f"persona-file:{filename}",
                                reason="persona_soft_cap",
                                original_estimated_tokens=original_tokens,
                                final_estimated_tokens=self._token_estimator.estimate(best_body),
                            )
                        )
                        truncated_sections.add(ContextSectionKind.PERSONA)

        def assemble() -> tuple[tuple[ContextSection, ...], str, int]:
            return self._assemble(
                request,
                memories=memories,
                memory_bodies=memory_bodies,
                persona_files=persona_files,
                project_history=project_history,
                task_history=task_history,
                truncated_sections=truncated_sections,
            )

        sections, rendered_context, estimated_tokens = assemble()
        usable_tokens = request.token_budget.usable_context_tokens

        while estimated_tokens > usable_tokens and len(memories) > 1:
            removed = memories.pop()
            change = self._dropped_memory_change(removed, "memory_budget")
            dropped_items.append(change)
            dropped_by_reason[change.reason] = (
                dropped_by_reason.get(change.reason, 0) + change.original_estimated_tokens
            )
            truncated_sections.add(ContextSectionKind.RELEVANT_MEMORY)
            sections, rendered_context, estimated_tokens = assemble()

        if estimated_tokens > usable_tokens and memories:
            memory = memories[0]
            original_body = memory.memory.summary or memory.memory.content
            original_block_tokens = self._token_estimator.estimate(
                self._render_memory_block(memory, original_body)
            )
            best_body: str | None = None
            low = 0
            high = max(len(original_body) - 1, 0)
            while low <= high:
                midpoint = (low + high) // 2
                candidate = self._truncated_text(original_body, midpoint)
                memory_bodies[memory.memory.id] = candidate
                _, _, candidate_tokens = assemble()
                if candidate_tokens <= usable_tokens:
                    best_body = candidate
                    low = midpoint + 1
                else:
                    high = midpoint - 1

            if best_body is None:
                memory_bodies.pop(memory.memory.id, None)
                removed = memories.pop()
                change = self._dropped_memory_change(removed, "memory_budget")
                dropped_items.append(change)
                dropped_by_reason[change.reason] = (
                    dropped_by_reason.get(change.reason, 0) + change.original_estimated_tokens
                )
            else:
                memory_bodies[memory.memory.id] = best_body
                final_block_tokens = self._token_estimator.estimate(
                    self._render_memory_block(memory, best_body)
                )
                truncated_items.append(
                    ContextItemChange(
                        section=ContextSectionKind.RELEVANT_MEMORY,
                        source_ref=f"memory:{memory.memory.id}",
                        reason="memory_body_budget",
                        original_estimated_tokens=original_block_tokens,
                        final_estimated_tokens=final_block_tokens,
                    )
                )
            truncated_sections.add(ContextSectionKind.RELEVANT_MEMORY)
            sections, rendered_context, estimated_tokens = assemble()

        while estimated_tokens > usable_tokens and project_history:
            index, value = project_history.pop(0)
            change = self._dropped_text_change(
                ContextSectionKind.PROJECT_CONTEXT,
                f"project:history:{index}",
                "project_history_budget",
                f"- {value}",
            )
            dropped_items.append(change)
            dropped_by_reason[change.reason] = (
                dropped_by_reason.get(change.reason, 0) + change.original_estimated_tokens
            )
            truncated_sections.add(ContextSectionKind.PROJECT_CONTEXT)
            sections, rendered_context, estimated_tokens = assemble()

        while estimated_tokens > usable_tokens and task_history:
            index, value = task_history.pop(0)
            change = self._dropped_text_change(
                ContextSectionKind.ACTIVE_TASK,
                f"task:history:{index}",
                "task_history_budget",
                f"- {value}",
            )
            dropped_items.append(change)
            dropped_by_reason[change.reason] = (
                dropped_by_reason.get(change.reason, 0) + change.original_estimated_tokens
            )
            truncated_sections.add(ContextSectionKind.ACTIVE_TASK)
            sections, rendered_context, estimated_tokens = assemble()

        example_files = [filename for filename in persona_files if "example" in filename.casefold()]
        while estimated_tokens > usable_tokens and example_files:
            filename = example_files.pop()
            persona_files.remove(filename)
            content = request.persona.files.get(filename, "")
            change = self._dropped_text_change(
                ContextSectionKind.PERSONA,
                f"persona-file:{filename}",
                "persona_example_budget",
                content,
            )
            dropped_items.append(change)
            dropped_by_reason[change.reason] = (
                dropped_by_reason.get(change.reason, 0) + change.original_estimated_tokens
            )
            truncated_sections.add(ContextSectionKind.PERSONA)
            sections, rendered_context, estimated_tokens = assemble()

        if estimated_tokens > usable_tokens:
            raise ContextBudgetExceededError(estimated_tokens, usable_tokens)

        dropped_estimated_tokens = sum(change.original_estimated_tokens for change in dropped_items)
        tokens_by_section = {section.kind: section.estimated_tokens for section in sections}
        return ContextBundle(
            sections=sections,
            rendered_context=rendered_context,
            token_budget=request.token_budget,
            estimated_tokens=estimated_tokens,
            remaining_tokens=usable_tokens - estimated_tokens,
            dropped_items=tuple(dropped_items),
            truncated_items=tuple(truncated_items),
            warnings=tuple(warnings),
            provenance=tuple(
                ContextProvenance(
                    section=section.kind,
                    source_refs=section.source_refs,
                )
                for section in sections
            ),
            candidate_estimated_tokens=candidate_estimated_tokens,
            dropped_estimated_tokens=dropped_estimated_tokens,
            reduction_pct=(
                (candidate_estimated_tokens - estimated_tokens) / candidate_estimated_tokens
                if candidate_estimated_tokens > 0
                else 0.0
            ),
            tokens_by_section=tokens_by_section,
            dropped_by_reason=dropped_by_reason,
        )

    def _retrieve_memories(
        self,
        request: ContextBuildRequest,
        warnings: list[str],
    ) -> list[HybridMemorySearchResult]:
        query = self._build_retrieval_query(request)
        try:
            return self._retriever.retrieve(
                query,
                scope_id=request.memory_scope_id,
                limit=self._memory_limit,
            )
        except (MemoryRepositoryError, SQLAlchemyError) as error:
            warnings.append(f"memory_retrieval_failed: {type(error).__name__}")
            return []

    def _assemble(
        self,
        request: ContextBuildRequest,
        *,
        memories: list[HybridMemorySearchResult],
        memory_bodies: dict[str, str],
        persona_files: list[str],
        project_history: list[tuple[int, str]],
        task_history: list[tuple[int, str]],
        truncated_sections: set[ContextSectionKind],
    ) -> tuple[tuple[ContextSection, ...], str, int]:
        contents = {
            ContextSectionKind.PERSONA: self._render_persona(
                request,
                persona_files,
            ),
            ContextSectionKind.ROUTING_DECISIONS: self._render_routing(request),
            ContextSectionKind.PROJECT_CONTEXT: self._render_project(request, project_history),
            ContextSectionKind.ACTIVE_TASK: self._render_task(request, task_history),
            ContextSectionKind.RELEVANT_MEMORY: self._render_memories(
                memories,
                memory_bodies,
            ),
            ContextSectionKind.CURRENT_REQUEST: self._text(request.current_request),
        }
        source_refs = self._source_refs(
            request,
            memories=memories,
            persona_files=persona_files,
            project_history=project_history,
            task_history=task_history,
        )
        sections = tuple(
            self._section(
                kind,
                contents[kind],
                source_refs[kind],
                truncated=kind in truncated_sections,
            )
            for kind in ContextSectionKind
        )
        rendered_context = self._render_sections(sections)
        return (
            sections,
            rendered_context,
            self._token_estimator.estimate(rendered_context),
        )

    def _source_refs(
        self,
        request: ContextBuildRequest,
        *,
        memories: list[HybridMemorySearchResult],
        persona_files: list[str],
        project_history: list[tuple[int, str]],
        task_history: list[tuple[int, str]],
    ) -> dict[ContextSectionKind, tuple[str, ...]]:
        project_refs: tuple[str, ...] = ()
        if request.project_context is not None:
            project_refs = (
                f"project:{request.project_context.identity}",
                *(f"project:history:{index}" for index, _ in project_history),
            )
        task_refs: tuple[str, ...] = ()
        if request.task_context is not None:
            task_refs = (
                f"task:{request.task_context.identity}",
                *(f"task:history:{index}" for index, _ in task_history),
            )
        return {
            ContextSectionKind.PERSONA: (
                f"persona:{request.persona.version}",
                *(f"persona-file:{filename}" for filename in persona_files),
            ),
            ContextSectionKind.ROUTING_DECISIONS: (
                f"fast-router:{request.fast_router_decision.rule_id}",
                (f"capability-router:{request.capability_decision.reason_code}"),
            ),
            ContextSectionKind.PROJECT_CONTEXT: project_refs,
            ContextSectionKind.ACTIVE_TASK: task_refs,
            ContextSectionKind.RELEVANT_MEMORY: self._memory_source_refs(memories),
            ContextSectionKind.CURRENT_REQUEST: ("request:current",),
        }

    def _prepare_memories(
        self,
        memories: Iterable[HybridMemorySearchResult],
    ) -> tuple[list[HybridMemorySearchResult], list[ContextItemChange]]:
        ordered = sorted(
            memories,
            key=lambda item: (-item.hybrid_score, item.memory.id),
        )
        unique: list[HybridMemorySearchResult] = []
        changes: list[ContextItemChange] = []
        seen_ids: set[str] = set()
        for result in ordered:
            memory_id = result.memory.id
            if memory_id in seen_ids:
                changes.append(self._dropped_memory_change(result, "duplicate_memory"))
                continue
            seen_ids.add(memory_id)
            unique.append(result)
        return unique, changes

    # --- TOKEN-2 relevance-first selection -------------------------------

    def _select_candidates(
        self,
        request: ContextBuildRequest,
        *,
        memories: list[HybridMemorySearchResult],
        persona_files: list[str],
        project_history: list[tuple[int, str]],
        task_history: list[tuple[int, str]],
    ) -> tuple[
        ContextBuildRequest,
        list[HybridMemorySearchResult],
        list[str],
        list[tuple[int, str]],
        list[tuple[int, str]],
        list[ContextItemChange],
    ]:
        changes: list[ContextItemChange] = []
        memories = list(memories)
        persona_files = list(persona_files)
        project_history = list(project_history)
        task_history = list(task_history)

        # 1. Direct-route guard: conversational/direct requests do not need
        # workflow-heavy project/task context. Routing + current request stay.
        if self._is_direct_conversational(request):
            if project_history:
                changes.extend(
                    self._dropped_text_change(
                        ContextSectionKind.PROJECT_CONTEXT,
                        f"project:history:{index}",
                        "low_relevance",
                        f"- {value}",
                    )
                    for index, value in project_history
                )
                project_history = []
            if task_history:
                changes.extend(
                    self._dropped_text_change(
                        ContextSectionKind.ACTIVE_TASK,
                        f"task:history:{index}",
                        "low_relevance",
                        f"- {value}",
                    )
                    for index, value in task_history
                )
                task_history = []

        # 2. Persona files: keep safety-critical files first; drop
        # non-critical files from the end when over the soft cap.
        critical = {name.casefold() for name in ("SAFETY", "POLICY", "RULES", "IDENTITY")}
        noncritical: list[tuple[int, str]] = []
        kept_files: list[str] = []
        for index, filename in enumerate(persona_files):
            stem = filename.rsplit(".", 1)[0].casefold()
            if stem in critical:
                kept_files.append(filename)
            else:
                noncritical.append((index, filename))
        persona_files = kept_files + [name for _, name in noncritical]
        soft = request.token_budget.persona_soft_tokens
        if soft > 0:
            for _index, filename in reversed(noncritical):
                if self._persona_tokens(request, persona_files) <= soft:
                    break
                persona_files.remove(filename)
                content = request.persona.files.get(filename, "")
                changes.append(
                    self._dropped_text_change(
                        ContextSectionKind.PERSONA,
                        f"persona-file:{filename}",
                        "section_cap",
                        content,
                    )
                )

        # 3. Cross-section exact-string deduplication: identical redacted
        # content appearing in multiple sections is kept once.
        memory_bodies_seen: dict[str, str] = {}
        unique_memories: list[HybridMemorySearchResult] = []
        for memory_result in memories:
            body = memory_result.memory.summary or memory_result.memory.content
            if not body:
                unique_memories.append(memory_result)
                continue
            redacted = self._text(body)
            if redacted in memory_bodies_seen:
                changes.append(self._dropped_memory_change(memory_result, "duplicate"))
                continue
            memory_bodies_seen[redacted] = memory_result.memory.id
            unique_memories.append(memory_result)
        memories = unique_memories

        def dedupe_tuple(values, section, source_prefix):
            kept = []
            for index, value in enumerate(values):
                redacted = self._text(value)
                if redacted in memory_bodies_seen:
                    changes.append(
                        self._dropped_text_change(
                            section, f"{source_prefix}:{index}", "duplicate", redacted
                        )
                    )
                    continue
                memory_bodies_seen[redacted] = f"{source_prefix}:{index}"
                kept.append(value)
            return tuple(kept)

        def dedupe_optional(value, section, source_ref):
            if not value:
                return value
            redacted = self._text(value)
            if redacted in memory_bodies_seen:
                changes.append(
                    self._dropped_text_change(section, source_ref, "duplicate", redacted)
                )
                return None
            memory_bodies_seen[redacted] = source_ref
            return value

        def dedupe_history(values, section, source_prefix):
            kept: list[tuple[int, str]] = []
            for index, value in values:
                redacted = self._text(value)
                source_ref = f"{source_prefix}:{index}"
                if redacted in memory_bodies_seen:
                    changes.append(
                        self._dropped_text_change(section, source_ref, "duplicate", redacted)
                    )
                    continue
                memory_bodies_seen[redacted] = source_ref
                kept.append((index, value))
            return kept

        if request.project_context is not None:
            project = request.project_context
            project_history = dedupe_history(
                project_history,
                ContextSectionKind.PROJECT_CONTEXT,
                "project:history",
            )
            project = project.model_copy(
                update={
                    "goal": dedupe_optional(
                        project.goal, ContextSectionKind.PROJECT_CONTEXT, "project:goal"
                    ),
                    "current_phase": dedupe_optional(
                        project.current_phase,
                        ContextSectionKind.PROJECT_CONTEXT,
                        "project:current_phase",
                    ),
                    "architecture_constraints": dedupe_tuple(
                        project.architecture_constraints,
                        ContextSectionKind.PROJECT_CONTEXT,
                        "project:architecture_constraint",
                    ),
                    "decisions": dedupe_tuple(
                        project.decisions, ContextSectionKind.PROJECT_CONTEXT, "project:decision"
                    ),
                    "status": dedupe_optional(
                        project.status, ContextSectionKind.PROJECT_CONTEXT, "project:status"
                    ),
                    "history": tuple(value for _, value in project_history),
                }
            )
            request = request.model_copy(update={"project_context": project})

        if request.task_context is not None:
            task = request.task_context
            task_history = dedupe_history(
                task_history,
                ContextSectionKind.ACTIVE_TASK,
                "task:history",
            )
            task = task.model_copy(
                update={
                    "status": dedupe_optional(
                        task.status, ContextSectionKind.ACTIVE_TASK, "task:status"
                    ),
                    "constraints": dedupe_tuple(
                        task.constraints, ContextSectionKind.ACTIVE_TASK, "task:constraint"
                    ),
                    "acceptance_criteria": dedupe_tuple(
                        task.acceptance_criteria,
                        ContextSectionKind.ACTIVE_TASK,
                        "task:acceptance_criterion",
                    ),
                    "blockers": dedupe_tuple(
                        task.blockers, ContextSectionKind.ACTIVE_TASK, "task:blocker"
                    ),
                    "next_action": dedupe_optional(
                        task.next_action, ContextSectionKind.ACTIVE_TASK, "task:next_action"
                    ),
                    "history": tuple(value for _, value in task_history),
                }
            )
            request = request.model_copy(update={"task_context": task})

        # 4. Memory ranking: relevance + scope + recency + importance, with
        # a stable id tie-breaker. Scope-specific memory outranks generic.
        memory_scope_id = request.memory_scope_id
        memories.sort(
            key=lambda item: (
                -item.hybrid_score,
                -(
                    1.0
                    if (memory_scope_id is not None and item.memory.scope_id == memory_scope_id)
                    else 0.0
                ),
                -item.recency_score,
                -item.importance_score,
                item.memory.id,
            )
        )

        # 5. Low-relevance memory trimming: when memory alone exceeds its
        # soft cap, drop lowest-ranked memories first (never the last one).
        memory_soft = request.token_budget.memory_soft_tokens
        if memory_soft > 0 and len(memories) > 1:
            while self._memories_tokens(request, memories) > memory_soft and len(memories) > 1:
                removed = memories.pop()
                changes.append(self._dropped_memory_change(removed, "low_relevance"))

        return (
            request,
            memories,
            persona_files,
            project_history,
            task_history,
            changes,
        )

    def _is_direct_conversational(
        self,
        request: ContextBuildRequest,
    ) -> bool:
        return (
            request.fast_router_decision.route is FastRoute.DIRECT
            and request.capability_decision.capability is CapabilityKind.CONVERSATIONAL_RESPONSE
        )

    def _memories_tokens(
        self,
        request: ContextBuildRequest,
        memories: Sequence[HybridMemorySearchResult],
    ) -> int:
        return sum(
            self._token_estimator.estimate(
                self._render_memory_block(
                    result,
                    result.memory.summary or result.memory.content,
                )
            )
            for result in memories
        )

    def _persona_tokens(
        self,
        request: ContextBuildRequest,
        persona_files: list[str],
    ) -> int:
        return self._token_estimator.estimate(self._render_persona(request, persona_files))

    def _candidate_tokens(
        self,
        request: ContextBuildRequest,
        *,
        memories: list[HybridMemorySearchResult],
        persona_files: list[str],
        project_history: list[tuple[int, str]],
        task_history: list[tuple[int, str]],
        dropped_items: list[ContextItemChange],
    ) -> int:
        _, rendered_context, _ = self._assemble(
            request,
            memories=memories,
            memory_bodies={},
            persona_files=persona_files,
            project_history=project_history,
            task_history=task_history,
            truncated_sections=set(),
        )
        total = self._token_estimator.estimate(rendered_context)
        for change in dropped_items:
            if change.final_estimated_tokens == 0:
                total += change.original_estimated_tokens
        return total

    def _dropped_memory_change(
        self,
        result: HybridMemorySearchResult,
        reason: str,
    ) -> ContextItemChange:
        body = result.memory.summary or result.memory.content
        return ContextItemChange(
            section=ContextSectionKind.RELEVANT_MEMORY,
            source_ref=f"memory:{result.memory.id}",
            reason=reason,
            original_estimated_tokens=self._token_estimator.estimate(
                self._render_memory_block(result, body)
            ),
            final_estimated_tokens=0,
        )

    def _dropped_text_change(
        self,
        section: ContextSectionKind,
        source_ref: str,
        reason: str,
        content: str,
    ) -> ContextItemChange:
        return ContextItemChange(
            section=section,
            source_ref=source_ref,
            reason=reason,
            original_estimated_tokens=self._token_estimator.estimate(content),
            final_estimated_tokens=0,
        )

    def _section(
        self,
        kind: ContextSectionKind,
        content: str,
        source_refs: tuple[str, ...],
        *,
        truncated: bool,
    ) -> ContextSection:
        chunk = self._render_chunk(kind, content)
        return ContextSection(
            kind=kind,
            content=content,
            priority=_SECTION_PRIORITIES[kind],
            estimated_tokens=self._token_estimator.estimate(chunk),
            source_refs=source_refs,
            truncated=truncated,
        )

    def _build_retrieval_query(self, request: ContextBuildRequest) -> str:
        lines = [f"current_request: {self._text(request.current_request)}"]
        if request.task_context is not None:
            lines.append(f"active_task_goal: {self._text(request.task_context.active_goal)}")
        if request.project_context is not None:
            lines.append(f"project_identity: {self._text(request.project_context.identity)}")
            if request.project_context.goal:
                lines.append(f"project_goal: {self._text(request.project_context.goal)}")
        lines.extend(
            (
                f"fast_route: {request.fast_router_decision.route.value}",
                (f"capability: {request.capability_decision.capability.value}"),
            )
        )
        return "\n".join(lines)

    def _render_persona(
        self,
        request: ContextBuildRequest,
        persona_files: list[str],
    ) -> str:
        persona = request.persona
        lines = [
            f"version: {self._text(persona.version)}",
            f"language: {self._text(persona.language)}",
            f"relationship: {self._text(persona.relationship)}",
            f"tone: {self._text(persona.tone)}",
        ]
        for filename in persona_files:
            content = persona.files.get(filename)
            if content:
                lines.append(f"\n--- {self._text(filename)} ---\n{self._text(content)}")
        if len(lines) == 4 and not persona.file_order and persona.combined_content:
            lines.append(self._text(persona.combined_content))
        return "\n".join(lines)

    def _render_routing(self, request: ContextBuildRequest) -> str:
        fast = request.fast_router_decision
        capability = request.capability_decision
        signals = ", ".join(self._text(item) for item in capability.matched_signals)
        return "\n".join(
            (
                "Fast Router:",
                f"- selected_route: {fast.route.value}",
                f"- rule_id: {self._text(fast.rule_id)}",
                f"- reason: {self._text(fast.reason)}",
                "Capability Router:",
                f"- selected_capability: {capability.capability.value}",
                f"- source_route: {capability.source_route.value}",
                f"- reason_code: {self._text(capability.reason_code)}",
                f"- matched_signals: {signals or 'none'}",
            )
            + self._render_runtime_policy_lines(request)
        )

    def _render_runtime_policy_lines(
        self,
        request: ContextBuildRequest,
    ) -> tuple[str, ...]:
        runtime_policy = request.runtime_policy
        if request.fast_router_decision.route.value != "workflow" or runtime_policy is None:
            return ()
        folded = request.current_request.casefold()
        if not runtime_policy.approval_required and not any(
            marker in folded
            for marker in (
                "approval",
                "duyệt",
                "publish",
                "send external",
                "facebook",
                "web research",
                "web search",
                "capability",
                "quyền",
                "có thể",
            )
        ):
            return ()
        return (
            "Runtime Policy:",
            f"- effective_risk_level: {int(runtime_policy.risk_level)}",
            f"- approval_required: {str(runtime_policy.approval_required).lower()}",
            f"- policy_decision: {runtime_policy.policy_decision.value}",
            f"- policy_rule_id: {self._text(runtime_policy.policy_rule_id)}",
            f"- policy_reason: {self._text(runtime_policy.policy_reason)}",
            "- safe_without_approval: " + ", ".join(SAFE_STEPS_WITHOUT_APPROVAL),
            "- step_gate: " + ", ".join(HARD_APPROVAL_GATED_STEPS),
            "- execution_constraint: " + ", ".join(STEP_LEVEL_EXECUTION_CONSTRAINTS),
        )

    def _render_project(
        self,
        request: ContextBuildRequest,
        history: list[tuple[int, str]],
    ) -> str:
        project = request.project_context
        if project is None:
            return "none"
        lines = [f"identity: {self._text(project.identity)}"]
        self._append_optional(lines, "goal", project.goal)
        self._append_optional(lines, "current_phase", project.current_phase)
        self._append_items(
            lines,
            "architecture_constraints",
            project.architecture_constraints,
        )
        self._append_items(lines, "decisions", project.decisions)
        self._append_optional(lines, "status", project.status)
        self._append_items(lines, "history", tuple(value for _, value in history))
        return "\n".join(lines)

    def _render_task(
        self,
        request: ContextBuildRequest,
        history: list[tuple[int, str]],
    ) -> str:
        task = request.task_context
        if task is None:
            return "none"
        lines = [
            f"identity: {self._text(task.identity)}",
            f"active_goal: {self._text(task.active_goal)}",
        ]
        self._append_optional(lines, "status", task.status)
        self._append_items(lines, "constraints", task.constraints)
        self._append_items(lines, "acceptance_criteria", task.acceptance_criteria)
        self._append_items(lines, "blockers", task.blockers)
        self._append_optional(lines, "next_action", task.next_action)
        self._append_items(lines, "history", tuple(value for _, value in history))
        return "\n".join(lines)

    def _render_memories(
        self,
        memories: Iterable[HybridMemorySearchResult],
        memory_bodies: dict[str, str],
    ) -> str:
        blocks = [
            self._render_memory_block(
                result,
                memory_bodies.get(
                    result.memory.id,
                    result.memory.summary or result.memory.content,
                ),
            )
            for result in memories
        ]
        return "\n\n".join(blocks) if blocks else "none"

    def _render_memory_block(
        self,
        result: HybridMemorySearchResult,
        body: str,
    ) -> str:
        memory = result.memory
        source = self._text(memory.source) if memory.source else "unknown"
        return "\n".join(
            (
                f"- id: {self._text(memory.id)}",
                f"  title: {self._text(memory.title)}",
                f"  score: {result.hybrid_score:.6f}",
                f"  source: {source}",
                f"  content: {self._text(body)}",
            )
        )

    def _memory_source_refs(
        self,
        memories: Iterable[HybridMemorySearchResult],
    ) -> tuple[str, ...]:
        refs: list[str] = []
        for result in memories:
            refs.append(f"memory:{result.memory.id}")
            if result.memory.source:
                refs.append(f"memory-source:{result.memory.source}")
        return tuple(refs)

    @staticmethod
    def _indexed_project_history(
        request: ContextBuildRequest,
    ) -> list[tuple[int, str]]:
        if request.project_context is None:
            return []
        return list(enumerate(request.project_context.history))

    @staticmethod
    def _indexed_task_history(
        request: ContextBuildRequest,
    ) -> list[tuple[int, str]]:
        if request.task_context is None:
            return []
        return list(enumerate(request.task_context.history))

    @staticmethod
    def _truncated_text(text: str, keep_characters: int) -> str:
        prefix = text[:keep_characters].rstrip()
        return f"{prefix}…" if prefix else "…"

    def _append_optional(
        self,
        lines: list[str],
        label: str,
        value: str | None,
    ) -> None:
        if value:
            lines.append(f"{label}: {self._text(value)}")

    def _append_items(
        self,
        lines: list[str],
        label: str,
        values: tuple[str, ...],
    ) -> None:
        if values:
            lines.append(f"{label}:")
            lines.extend(f"- {self._text(value)}" for value in values)

    def _text(self, value: str) -> str:
        return cast(str, self._redactor.redact(value))

    @staticmethod
    def _render_chunk(kind: ContextSectionKind, content: str) -> str:
        marker = _SECTION_MARKERS[kind]
        return f"{marker}\n{content}".rstrip()

    def _render_sections(self, sections: Iterable[ContextSection]) -> str:
        return "\n\n".join(
            self._render_chunk(section.kind, section.content) for section in sections
        )
