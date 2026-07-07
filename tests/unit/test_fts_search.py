"""Tests for FTS5 search and enhanced hybrid RRF search (T021)."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from nous.domain.memory.entities import Memory
from nous.domain.search.engine import SearchEngine, SearchQuery, SearchResult
from nous.domain.search.ranker import RRFRanker
from nous.domain.shared.result import Success


def _mem(
    key: str,
    content: str = "content",
    importance: float = 0.5,
    emotion: str = "neutral",
    created_at: datetime | None = None,
) -> Memory:
    now = datetime.now(UTC)
    return Memory(
        key=key,
        content=content,
        created_at=created_at or now,
        updated_at=now,
        importance=importance,
        emotion=emotion,
    )


def _result(key: str, score: float, source: str = "keyword", **kwargs) -> SearchResult:
    return SearchResult(memory=_mem(key, **kwargs), score=score, source=source)


# ---------------------------------------------------------------------------
# RRFRanker with source weights
# ---------------------------------------------------------------------------


class TestRRFRankerWeights:
    def test_vector_weight_applied_to_semantic(self):
        """vector_weight should boost semantic results in RRF."""
        ranker = RRFRanker(k=60)
        query = SearchQuery(text="test", vector_weight=2.0, keyword_weight=0.5)
        results = [
            _result("sem_key", score=0.9, source="semantic"),
            _result("kw_key", score=0.8, source="keyword"),
        ]
        ranked = ranker.rank(results, query)
        # sem_key should rank higher due to vector_weight=2.0
        assert ranked[0].memory.key == "sem_key"

    def test_keyword_weight_applied_to_fts_and_keyword(self):
        """keyword_weight should apply to both 'keyword' and 'fts' sources."""
        ranker = RRFRanker(k=60)
        query = SearchQuery(text="test", vector_weight=0.3, keyword_weight=2.0)
        results = [
            _result("sem_key", score=0.9, source="semantic"),
            _result("fts_key", score=0.8, source="fts"),
            _result("kw_key", score=0.7, source="keyword"),
        ]
        ranked = ranker.rank(results, query)
        # fts_key and kw_key share keyword_weight=2.0 → should dominate
        assert ranked[0].memory.key in ("fts_key", "kw_key")
        assert ranked[-1].memory.key == "sem_key"

    def test_default_weights_backward_compatible(self):
        """Old SearchQuery without vector_weight/keyword_weight should use defaults."""
        ranker = RRFRanker(k=60)
        # Simulate old SearchQuery (without new fields)
        query = SearchQuery(text="test")
        results = [
            _result("sem_key", score=0.9, source="semantic"),
            _result("kw_key", score=0.8, source="keyword"),
        ]
        ranked = ranker.rank(results, query)
        assert len(ranked) == 2

    def test_rrf_three_sources_fusion(self):
        """Three-source RRF fusion should work correctly."""
        ranker = RRFRanker(k=60)
        query = SearchQuery(text="test")
        # key_a appears in all three sources
        results = [
            _result("key_a", score=0.9, source="semantic"),
            _result("key_b", score=0.8, source="semantic"),
            _result("key_a", score=0.85, source="keyword"),
            _result("key_c", score=0.7, source="keyword"),
            _result("key_a", score=0.8, source="fts"),
            _result("key_d", score=0.6, source="fts"),
        ]
        ranked = ranker.rank(results, query)
        keys = [r.memory.key for r in ranked]
        # key_a in all 3 sources → highest RRF score
        assert keys[0] == "key_a"


# ---------------------------------------------------------------------------
# SearchEngine with FTS5 integration
# ---------------------------------------------------------------------------


class TestSearchEngineFTS5Hybrid:
    @pytest.mark.asyncio
    async def test_hybrid_includes_fts_when_memory_repo_available(self):
        """Hybrid search should include FTS5 results when memory_repo has search_fts."""
        mem_kw = _mem("kw_key")
        mem_fts = _mem("fts_key")
        mem_sem = _mem("sem_key")

        kw = MagicMock()
        kw.search.return_value = Success([(mem_kw, 0.7)])

        sem = AsyncMock()
        sem.search.return_value = Success([(mem_sem, 0.9)])

        memory_repo = MagicMock()
        memory_repo.search_fts.return_value = Success([(mem_fts, 0.85)])

        engine = SearchEngine(keyword_search=kw, semantic_search=sem, memory_repo=memory_repo)
        result = await engine.search(SearchQuery(text="hello", mode="hybrid", top_k=10))
        assert result.is_ok
        keys = {r.memory.key for r in result.value}
        assert "kw_key" in keys
        assert "fts_key" in keys
        assert "sem_key" in keys
        memory_repo.search_fts.assert_called_once()

    @pytest.mark.asyncio
    async def test_hybrid_fallback_when_no_fts(self):
        """Hybrid search should work without FTS5 (memory_repo without search_fts)."""
        mem_kw = _mem("kw_key")
        mem_sem = _mem("sem_key")

        kw = MagicMock()
        kw.search.return_value = Success([(mem_kw, 0.7)])

        sem = AsyncMock()
        sem.search.return_value = Success([(mem_sem, 0.9)])

        memory_repo = MagicMock()
        # memory_repo doesn't have search_fts attr → should be skipped
        del memory_repo.search_fts

        engine = SearchEngine(keyword_search=kw, semantic_search=sem, memory_repo=memory_repo)
        result = await engine.search(SearchQuery(text="hello", mode="hybrid", top_k=10))
        assert result.is_ok
        keys = {r.memory.key for r in result.value}
        assert "kw_key" in keys
        assert "sem_key" in keys

    @pytest.mark.asyncio
    async def test_fts_search_is_labeled_fts_source(self):
        """FTS5 results should have source='fts'."""
        mem = _mem("fts_key")
        kw = MagicMock()
        kw.search.return_value = Success([(_mem("kw_key"), 0.7)])
        sem = AsyncMock()
        sem.search.return_value = Success([])

        memory_repo = MagicMock()
        memory_repo.search_fts.return_value = Success([(mem, 0.85)])

        engine = SearchEngine(keyword_search=kw, semantic_search=sem, memory_repo=memory_repo)
        result = await engine.search(SearchQuery(text="hello", mode="hybrid", top_k=10))
        assert result.is_ok
        fts_results = [r for r in result.value if r.source == "fts"]
        assert len(fts_results) >= 1


# ---------------------------------------------------------------------------
# Semantic search similarity_flag
# ---------------------------------------------------------------------------


class TestSimilarityFlag:
    @pytest.mark.asyncio
    async def test_similarity_flag_set_when_above_threshold(self):
        """similarity_flag should be True when score >= similarity_threshold."""
        mem = _mem("sem_key")
        kw = MagicMock()
        kw.search.return_value = Success([])
        sem = AsyncMock()
        sem.search.return_value = Success([(mem, 0.9)])

        engine = SearchEngine(keyword_search=kw, semantic_search=sem)
        query = SearchQuery(text="hello", mode="hybrid", top_k=10, similarity_threshold=0.85)
        result = await engine.search(query)
        assert result.is_ok
        assert result.value[0].similarity_flag is True

    @pytest.mark.asyncio
    async def test_similarity_flag_not_set_when_below_threshold(self):
        """similarity_flag should be False when score < similarity_threshold."""
        mem = _mem("sem_key")
        kw = MagicMock()
        kw.search.return_value = Success([])
        sem = AsyncMock()
        sem.search.return_value = Success([(mem, 0.8)])

        engine = SearchEngine(keyword_search=kw, semantic_search=sem)
        query = SearchQuery(text="hello", mode="hybrid", top_k=10, similarity_threshold=0.85)
        result = await engine.search(query)
        assert result.is_ok
        assert result.value[0].similarity_flag is False

    @pytest.mark.asyncio
    async def test_similarity_flag_threshold_zero_disables_flag(self):
        """threshold=0 should disable similarity_flag (never set)."""
        mem = _mem("sem_key")
        kw = MagicMock()
        kw.search.return_value = Success([])
        sem = AsyncMock()
        sem.search.return_value = Success([(mem, 0.9)])

        engine = SearchEngine(keyword_search=kw, semantic_search=sem)
        query = SearchQuery(text="hello", mode="hybrid", top_k=10, similarity_threshold=0.0)
        result = await engine.search(query)
        assert result.is_ok
        assert result.value[0].similarity_flag is False

    @pytest.mark.asyncio
    async def test_similarity_flag_only_for_semantic(self):
        """Non-semantic results should never have similarity_flag set."""
        kw = MagicMock()
        kw.search.return_value = Success([(_mem("kw_key"), 0.7)])
        sem = AsyncMock()
        sem.search.return_value = Success([])

        engine = SearchEngine(keyword_search=kw, semantic_search=sem)
        query = SearchQuery(text="hello", mode="hybrid", top_k=10)
        result = await engine.search(query)
        assert result.is_ok
        assert result.value[0].similarity_flag is False


# ---------------------------------------------------------------------------
# SearchQuery backward compatibility
# ---------------------------------------------------------------------------


class TestSearchQueryNewFields:
    def test_new_fields_have_defaults(self):
        """New fields should have backward-compatible defaults."""
        q = SearchQuery(text="test")
        assert q.vector_weight == 1.0
        assert q.keyword_weight == 0.5
        assert q.similarity_threshold == 0.85

    def test_new_fields_positional_construction(self):
        """New fields should work with positional args after existing ones."""
        q = SearchQuery(
            text="test",
            mode="hybrid",
            top_k=10,
            vector_weight=2.0,
            keyword_weight=0.3,
            similarity_threshold=0.9,
        )
        assert q.vector_weight == 2.0
        assert q.keyword_weight == 0.3
        assert q.similarity_threshold == 0.9
