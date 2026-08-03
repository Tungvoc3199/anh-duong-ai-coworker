from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

from app.memory.models import MemorySearchResult, MemoryType
from app.memory.retrieval import HybridMemoryRetriever


def _candidate(
    *,
    memory_id: str,
    importance: float,
    confidence: float,
    updated_at: datetime,
    fts_rank: float,
) -> MemorySearchResult:
    return MemorySearchResult(
        id=memory_id,
        memory_type=MemoryType.PROJECT,
        scope_id="proj_1",
        title=f"Memory {memory_id}",
        content="Hybrid retrieval candidate",
        summary=None,
        importance=importance,
        confidence=confidence,
        source=None,
        expires_at=None,
        tags=(),
        created_at=updated_at,
        updated_at=updated_at,
        version=1,
        fts_rank=fts_rank,
    )


def test_metadata_can_promote_second_lexical_candidate() -> None:
    now = datetime(2026, 7, 25, 12, 0, tzinfo=UTC)
    candidate_a = _candidate(
        memory_id="mem_a",
        importance=0.0,
        confidence=0.0,
        updated_at=now - timedelta(days=300),
        fts_rank=-10.0,
    )
    candidate_b = _candidate(
        memory_id="mem_b",
        importance=1.0,
        confidence=1.0,
        updated_at=now,
        fts_rank=-5.0,
    )
    repository = Mock()
    repository.search_fts.return_value = [candidate_a, candidate_b]
    retriever = HybridMemoryRetriever(repository)

    results = retriever.retrieve(
        "hybrid retrieval",
        limit=2,
        now=now,
    )

    assert [result.memory.id for result in results] == ["mem_b", "mem_a"]


def test_retriever_is_exported_from_memory_package() -> None:
    from app.memory import HybridMemoryRetriever as ExportedHybridMemoryRetriever

    assert ExportedHybridMemoryRetriever is HybridMemoryRetriever


def test_empty_or_tokenless_query_skips_repository() -> None:
    repository = Mock()
    retriever = HybridMemoryRetriever(repository)

    assert retriever.retrieve("", limit=5) == []
    assert retriever.retrieve("___ !!!", limit=5) == []
    repository.search_fts.assert_not_called()


def test_candidate_limit_and_filters_are_forwarded() -> None:
    repository = Mock()
    repository.search_fts.return_value = []
    retriever = HybridMemoryRetriever(repository)

    results = retriever.retrieve(
        "memory query",
        scope_id="scope_1",
        memory_type=MemoryType.USER,
        limit=7,
        include_expired=True,
    )

    assert results == []
    repository.search_fts.assert_called_once_with(
        "memory query",
        scope_id="scope_1",
        memory_type=MemoryType.USER,
        limit=28,
        include_expired=True,
    )


def test_scores_are_clamped_and_future_memory_has_full_recency() -> None:
    now = datetime(2026, 7, 25, 12, 0, tzinfo=UTC)
    candidate = _candidate(
        memory_id="mem_clamped",
        importance=-2.0,
        confidence=3.0,
        updated_at=now + timedelta(days=30),
        fts_rank=-1.0,
    )
    repository = Mock()
    repository.search_fts.return_value = [candidate]
    retriever = HybridMemoryRetriever(repository)

    [result] = retriever.retrieve("clamp scores", limit=1, now=now)

    assert result.memory.id == "mem_clamped"
    assert result.fts_rank == -1.0
    assert result.lexical_score == 1.0
    assert result.importance_score == 0.0
    assert result.confidence_score == 1.0
    assert result.recency_score == 1.0
    assert 0.0 <= result.hybrid_score <= 1.0


def test_limit_is_applied_after_hybrid_ranking() -> None:
    now = datetime(2026, 7, 25, 12, 0, tzinfo=UTC)
    lexical_first = _candidate(
        memory_id="mem_lexical_first",
        importance=0.0,
        confidence=0.0,
        updated_at=now - timedelta(days=300),
        fts_rank=-10.0,
    )
    metadata_first = _candidate(
        memory_id="mem_metadata_first",
        importance=1.0,
        confidence=1.0,
        updated_at=now,
        fts_rank=-5.0,
    )
    repository = Mock()
    repository.search_fts.return_value = [lexical_first, metadata_first]
    retriever = HybridMemoryRetriever(repository)

    results = retriever.retrieve("rank then limit", limit=1, now=now)

    assert [result.memory.id for result in results] == ["mem_metadata_first"]
    repository.search_fts.assert_called_once_with(
        "rank then limit",
        scope_id=None,
        memory_type=None,
        limit=20,
        include_expired=False,
    )


def test_stable_sort_uses_memory_id_after_other_ties() -> None:
    now = datetime(2026, 7, 25, 12, 0, tzinfo=UTC)
    dummy_first = _candidate(
        memory_id="mem_dummy_first",
        importance=1.0,
        confidence=1.0,
        updated_at=now,
        fts_rank=-20.0,
    )
    tie_b = _candidate(
        memory_id="mem_b",
        importance=0.5,
        confidence=0.0,
        updated_at=now,
        fts_rank=-5.0,
    )
    dummy_middle = _candidate(
        memory_id="mem_dummy_middle",
        importance=0.0,
        confidence=0.0,
        updated_at=now - timedelta(days=365),
        fts_rank=-1.0,
    )
    tie_a = _candidate(
        memory_id="mem_a",
        importance=0.5,
        confidence=1.0,
        updated_at=now,
        fts_rank=-5.0,
    )
    repository = Mock()
    repository.search_fts.return_value = [
        dummy_first,
        tie_b,
        dummy_middle,
        tie_a,
    ]
    retriever = HybridMemoryRetriever(repository)

    results = retriever.retrieve("stable tie", limit=4, now=now)
    result_ids = [result.memory.id for result in results]

    assert result_ids.index("mem_a") < result_ids.index("mem_b")


def test_same_candidates_and_now_are_deterministic() -> None:
    now = datetime(2026, 7, 25, 12, 0, tzinfo=UTC)
    candidates = [
        _candidate(
            memory_id="mem_a",
            importance=0.3,
            confidence=0.8,
            updated_at=now - timedelta(days=10),
            fts_rank=-8.0,
        ),
        _candidate(
            memory_id="mem_b",
            importance=0.9,
            confidence=0.4,
            updated_at=now - timedelta(days=2),
            fts_rank=-4.0,
        ),
    ]
    repository = Mock()
    repository.search_fts.return_value = candidates
    retriever = HybridMemoryRetriever(repository)

    first = retriever.retrieve("deterministic", limit=2, now=now)
    second = retriever.retrieve("deterministic", limit=2, now=now)

    assert first == second
