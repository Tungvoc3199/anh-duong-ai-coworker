from __future__ import annotations

from app.context_builder._builder_impl import (
    ContextBuilder as _ContextBuilder,
)
from app.context_builder.models import (
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
        return bundle.model_copy(
            update={
                "sections": sections,
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

