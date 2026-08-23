"""Cache-aware memory retrieval."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from app.memory.repository import MemoryNotFound

if TYPE_CHECKING:
    from app.cache.service import CacheService
    from app.memory.models import Memory, MemoryType
    from app.memory.retrieval import HybridMemoryRetriever, HybridMemorySearchResult


class CachedMemoryRetriever:
    """Wrapper for HybridMemoryRetriever with reference-only L2 cache payloads."""

    def __init__(
        self,
        retriever: HybridMemoryRetriever,
        cache_service: CacheService | None,
        ttl_seconds: float,
    ) -> None:
        self._retriever = retriever
        self._cache_service = cache_service
        self._ttl_seconds = ttl_seconds

    def retrieve(
        self,
        query: str,
        *,
        scope_id: str | None = None,
        memory_type: MemoryType | str | None = None,
        limit: int = 20,
        include_expired: bool = False,
        now: datetime | None = None,
    ) -> list[HybridMemorySearchResult]:
        """Retrieve memories with optional reference-only cache hydration."""
        if self._cache_service is None:
            return self._retrieve(
                query,
                scope_id=scope_id,
                memory_type=memory_type,
                limit=limit,
                include_expired=include_expired,
                now=now,
            )

        key_data = {
            "query": query,
            "scope_id": scope_id or "global",
            "memory_type": str(memory_type) if memory_type else "all",
            "limit": limit,
            "include_expired": include_expired,
        }
        # scope_id is the repository's required isolation boundary: all retrieval
        # queries are filtered by this exact field, and it is hashed before L2 use.
        dependencies = {"scope_id": scope_id or "global"}
        result = self._cache_service.get("memory.retrieval", key_data, dependencies)
        if result.outcome == "hit":
            hydrated = self._hydrate(result.payload, scope_id, memory_type, include_expired, now)
            if hydrated is not None:
                return hydrated

        retrieval_results = self._retrieve(
            query,
            scope_id=scope_id,
            memory_type=memory_type,
            limit=limit,
            include_expired=include_expired,
            now=now,
        )
        self._cache_service.put(
            "memory.retrieval",
            key_data,
            dependencies,
            self._serialize(retrieval_results),
            ttl_seconds=self._ttl_seconds,
        )
        return retrieval_results

    def _retrieve(
        self,
        query: str,
        *,
        scope_id: str | None,
        memory_type: MemoryType | str | None,
        limit: int,
        include_expired: bool,
        now: datetime | None,
    ) -> list[HybridMemorySearchResult]:
        return self._retriever.retrieve(
            query,
            scope_id=scope_id,
            memory_type=memory_type,
            limit=limit,
            include_expired=include_expired,
            now=now,
        )

    @staticmethod
    def _serialize(results: list[HybridMemorySearchResult]) -> list[dict[str, Any]]:
        """Store only memory references and ranking metadata; never memory text."""
        return [
            {
                "memory_id": result.memory.id,
                "memory_version": result.memory.version,
                "fts_rank": result.fts_rank,
                "lexical_score": result.lexical_score,
                "importance_score": result.importance_score,
                "confidence_score": result.confidence_score,
                "recency_score": result.recency_score,
                "hybrid_score": result.hybrid_score,
            }
            for result in results
        ]

    def _hydrate(
        self,
        payload: Any,
        scope_id: str | None,
        memory_type: MemoryType | str | None,
        include_expired: bool,
        now: datetime | None,
    ) -> list[HybridMemorySearchResult] | None:
        """Hydrate references from Core DB; any mismatch becomes a normal miss."""
        if not isinstance(payload, list):
            return None
        from app.memory.retrieval import HybridMemorySearchResult

        reference_now = now or datetime.now(UTC)
        hydrated: list[HybridMemorySearchResult] = []
        for item in payload:
            if not isinstance(item, dict) or not isinstance(item.get("memory_id"), str):
                return None
            try:
                memory = self._retriever._repository.get(item["memory_id"])
            except MemoryNotFound:
                return None
            if not self._valid_memory(
                memory,
                item,
                scope_id,
                memory_type,
                include_expired,
                reference_now,
            ):
                return None
            try:
                hydrated.append(
                    HybridMemorySearchResult(
                        memory=memory,
                        fts_rank=float(item["fts_rank"]),
                        lexical_score=float(item["lexical_score"]),
                        importance_score=float(item["importance_score"]),
                        confidence_score=float(item["confidence_score"]),
                        recency_score=float(item["recency_score"]),
                        hybrid_score=float(item["hybrid_score"]),
                    )
                )
            except (KeyError, TypeError, ValueError):
                return None
        return hydrated

    @staticmethod
    def _valid_memory(
        memory: Memory,
        item: dict[str, Any],
        scope_id: str | None,
        memory_type: MemoryType | str | None,
        include_expired: bool,
        reference_now: datetime,
    ) -> bool:
        if memory.version != item.get("memory_version"):
            return False
        if scope_id is not None and memory.scope_id != scope_id:
            return False
        if memory_type is not None:
            from app.memory.models import MemoryType

            if memory.memory_type != MemoryType(memory_type):
                return False
        return include_expired or memory.expires_at is None or memory.expires_at > reference_now
