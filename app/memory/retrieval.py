from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from app.memory.models import Memory, MemorySearchResult, MemoryType

_FTS_TOKEN_PATTERN = re.compile(r"[^\W_]+", flags=re.UNICODE)


class MemorySearchRepository(Protocol):
    def search_fts(
        self,
        query: str,
        *,
        scope_id: str | None = None,
        memory_type: MemoryType | str | None = None,
        limit: int = 20,
        include_expired: bool = False,
    ) -> list[MemorySearchResult]: ...


@dataclass(frozen=True, slots=True)
class HybridMemorySearchResult:
    memory: Memory
    fts_rank: float
    lexical_score: float
    importance_score: float
    confidence_score: float
    recency_score: float
    hybrid_score: float


class HybridMemoryRetriever:
    def __init__(self, repository: MemorySearchRepository) -> None:
        self._repository = repository

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
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")

        if _FTS_TOKEN_PATTERN.search(query.casefold()) is None:
            return []

        candidate_limit = min(max(limit * 4, 20), 100)
        candidates = self._repository.search_fts(
            query,
            scope_id=scope_id,
            memory_type=memory_type,
            limit=candidate_limit,
            include_expired=include_expired,
        )

        reference_now = self._normalize_datetime(now or datetime.now(UTC))
        ranked = [
            self._score_candidate(
                candidate,
                zero_based_fts_position=position,
                now=reference_now,
            )
            for position, candidate in enumerate(candidates)
        ]

        ranked.sort(key=self._sort_key)
        return ranked[:limit]

    @classmethod
    def _score_candidate(
        cls,
        candidate: MemorySearchResult,
        *,
        zero_based_fts_position: int,
        now: datetime,
    ) -> HybridMemorySearchResult:
        lexical_score = 1.0 / (1.0 + zero_based_fts_position)
        importance_score = cls._clamp(candidate.importance)
        confidence_score = cls._clamp(candidate.confidence)

        updated_at = cls._normalize_datetime(candidate.updated_at)
        age_days = max(
            (now - updated_at).total_seconds() / 86400.0,
            0.0,
        )
        recency_score = 1.0 / (1.0 + age_days / 30.0)

        hybrid_score = cls._clamp(
            0.60 * lexical_score
            + 0.15 * importance_score
            + 0.15 * confidence_score
            + 0.10 * recency_score
        )

        return HybridMemorySearchResult(
            memory=candidate,
            fts_rank=candidate.fts_rank,
            lexical_score=lexical_score,
            importance_score=importance_score,
            confidence_score=confidence_score,
            recency_score=recency_score,
            hybrid_score=hybrid_score,
        )

    @classmethod
    def _sort_key(
        cls,
        result: HybridMemorySearchResult,
    ) -> tuple[float, float, float, float, str]:
        updated_at = cls._normalize_datetime(result.memory.updated_at)
        return (
            -result.hybrid_score,
            result.fts_rank,
            -result.memory.importance,
            -updated_at.timestamp(),
            result.memory.id,
        )

    @staticmethod
    def _clamp(value: float) -> float:
        return min(max(value, 0.0), 1.0)

    @staticmethod
    def _normalize_datetime(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value
