from __future__ import annotations

from app.context_builder._builder_impl import (
    ContextBuilder as _ContextBuilder,
)
from app.context_builder.models import (
    ContextBudgetExceededError,
    ContextBuildRequest,
    ContextBundle,
    ContextItemChange,
    ContextProvenance,
    ContextSection,
    ContextSectionKind,
)


class ContextBuilder(_ContextBuilder):
    """Public CB-1 service with secret-safe observability metadata."""

    def build(self, request: ContextBuildRequest) -> ContextBundle:
        bundle = super().build(request)
        truncated_items = tuple(
            self._sanitize_change(item) for item in bundle.truncated_items
        )
        has_truncated_memory = any(
            item.section is ContextSectionKind.RELEVANT_MEMORY
            for item in truncated_items
        )
        sections = tuple(
            self._sanitize_section(
                section,
                has_truncated_memory=has_truncated_memory,
            )
            for section in bundle.sections
        )
        if request.attachment_context:
            sections = tuple(
                self._with_attachment_context(section, request)
                if section.kind is ContextSectionKind.CURRENT_REQUEST
                else section
                for section in sections
            )
        rendered_context = self._render_sections(sections)
        estimated_tokens = self._token_estimator.estimate(rendered_context)
        usable_tokens = bundle.token_budget.usable_context_tokens
        if estimated_tokens > usable_tokens:
            raise ContextBudgetExceededError(estimated_tokens, usable_tokens)
        return bundle.model_copy(
            update={
                "sections": sections,
                "rendered_context": rendered_context,
                "estimated_tokens": estimated_tokens,
                "remaining_tokens": usable_tokens - estimated_tokens,
                "dropped_items": tuple(
                    self._sanitize_change(item)
                    for item in bundle.dropped_items
                ),
                "truncated_items": truncated_items,
                "provenance": tuple(
                    ContextProvenance(
                        section=section.kind,
                        source_refs=section.source_refs,
                    )
                    for section in sections
                ),
            }
        )

    def _with_attachment_context(
        self,
        section: ContextSection,
        request: ContextBuildRequest,
    ) -> ContextSection:
        lines = [section.content, "", "Attachments:"]
        lines.extend(
            f"- {self._text(item)}" for item in request.attachment_context
        )
        content = "\n".join(lines)
        source_refs = (
            *section.source_refs,
            *(
                f"attachment:{index}"
                for index, _ in enumerate(request.attachment_context)
            ),
        )
        return section.model_copy(
            update={
                "content": content,
                "estimated_tokens": self._token_estimator.estimate(
                    self._render_chunk(section.kind, content)
                ),
                "source_refs": source_refs,
            }
        )

    def _sanitize_change(self, item: ContextItemChange) -> ContextItemChange:
        return item.model_copy(
            update={"source_ref": self._text(item.source_ref)}
        )

    def _sanitize_section(
        self,
        section: ContextSection,
        *,
        has_truncated_memory: bool,
    ) -> ContextSection:
        truncated = section.truncated
        if (
            section.kind is ContextSectionKind.RELEVANT_MEMORY
            and section.content == "none"
            and not has_truncated_memory
        ):
            truncated = False
        return section.model_copy(
            update={
                "source_refs": tuple(
                    self._text(source_ref)
                    for source_ref in section.source_refs
                ),
                "truncated": truncated,
            }
        )
