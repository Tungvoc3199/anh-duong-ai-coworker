from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol, cast

from sqlalchemy.exc import SQLAlchemyError

from app.audit.redaction import SecretRedactor
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
            dropped_items.append(
                self._dropped_memory_change(removed, "memory_budget")
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
                dropped_items.append(
                    self._dropped_memory_change(removed, "memory_budget")
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
            dropped_items.append(
                self._dropped_text_change(
                    ContextSectionKind.PROJECT_CONTEXT,
                    f"project:history:{index}",
                    "project_history_budget",
                    f"- {value}",
                )
            )
            truncated_sections.add(ContextSectionKind.PROJECT_CONTEXT)
            sections, rendered_context, estimated_tokens = assemble()

        while estimated_tokens > usable_tokens and task_history:
            index, value = task_history.pop(0)
            dropped_items.append(
                self._dropped_text_change(
                    ContextSectionKind.ACTIVE_TASK,
                    f"task:history:{index}",
                    "task_history_budget",
                    f"- {value}",
                )
            )
            truncated_sections.add(ContextSectionKind.ACTIVE_TASK)
            sections, rendered_context, estimated_tokens = assemble()

        example_files = [
            filename
            for filename in persona_files
            if "example" in filename.casefold()
        ]
        while estimated_tokens > usable_tokens and example_files:
            filename = example_files.pop()
            persona_files.remove(filename)
            content = request.persona.files.get(filename, "")
            dropped_items.append(
                self._dropped_text_change(
                    ContextSectionKind.PERSONA,
                    f"persona-file:{filename}",
                    "persona_example_budget",
                    content,
                )
            )
            truncated_sections.add(ContextSectionKind.PERSONA)
            sections, rendered_context, estimated_tokens = assemble()

        if estimated_tokens > usable_tokens:
            raise ContextBudgetExceededError(estimated_tokens, usable_tokens)

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
            warnings.append(
                f"memory_retrieval_failed: {type(error).__name__}"
            )
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
            ContextSectionKind.PROJECT_CONTEXT: self._render_project(
                request,
                project_history,
            ),
            ContextSectionKind.ACTIVE_TASK: self._render_task(
                request,
                task_history,
            ),
            ContextSectionKind.RELEVANT_MEMORY: self._render_memories(
                memories,
                memory_bodies,
            ),
            ContextSectionKind.CURRENT_REQUEST: self._text(
                request.current_request
            ),
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
                (
                    "capability-router:"
                    f"{request.capability_decision.reason_code}"
                ),
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
                changes.append(
                    self._dropped_memory_change(result, "duplicate_memory")
                )
                continue
            seen_ids.add(memory_id)
            unique.append(result)
        return unique, changes

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
            lines.append(
                f"active_task_goal: {self._text(request.task_context.active_goal)}"
            )
        if request.project_context is not None:
            lines.append(
                f"project_identity: {self._text(request.project_context.identity)}"
            )
            if request.project_context.goal:
                lines.append(
                    f"project_goal: {self._text(request.project_context.goal)}"
                )
        lines.extend(
            (
                f"fast_route: {request.fast_router_decision.route.value}",
                (
                    "capability: "
                    f"{request.capability_decision.capability.value}"
                ),
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
                lines.append(
                    f"\n--- {self._text(filename)} ---\n{self._text(content)}"
                )
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
            self._render_chunk(section.kind, section.content)
            for section in sections
        )

