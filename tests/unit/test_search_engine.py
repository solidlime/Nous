"""Tests for SearchEngine, RRFRanker, and ForgettingCurveRanker."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from nous.domain.memory.entities import Memory
from nous.domain.search.engine import SearchEngine, SearchQuery, SearchResult
from nous.domain.search.ranker import ForgettingCurveRanker, RRFRanker
from nous.domain.shared.result import Failure, Success

UTC = UTC


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mem(
    key: str,
    content: str = "content",
    importance: float = 0.5,
    emotion: str = "neutral",
    created_at: datetime | None = None,
    updated_at: datetime | None = None,
    tags: list[str] | None = None,
) -> Memory:
    now = datetime.now(UTC)
    return Memory(
        key=key,
        content=content,
        created_at=created_at or now,
        updated_at=updated_at or now,
        importance=importance,
        emotion=emotion,
        tags=tags or [],
    )


def _result(key: str, score: float, source: str = "keyword", **kwargs) -> SearchResult:
    return SearchResult(memory=_mem(key, **kwargs), score=score, source=source)


# ---------------------------------------------------------------------------
# RRFRanker
# ---------------------------------------------------------------------------


class TestRRFRanker:
    def test_empty_results_returns_empty(self):
        ranker = RRFRanker()
        query = SearchQuery(text="test")
        assert ranker.rank([], query) == []

    def test_single_source_ranking(self):
        ranker = RRFRanker(k=60)
        query = SearchQuery(text="test")
        results = [
            _result("key_a", score=0.9, source="keyword"),
            _result("key_b", score=0.5, source="keyword"),
            _result("key_c", score=0.1, source="keyword"),
        ]
        ranked = ranker.rank(results, query)
        # Higher-scored items should still rank higher via RRF
        assert len(ranked) == 3
        assert ranked[0].memory.key == "key_a"
        assert ranked[-1].memory.key == "key_c"
        for r in ranked:
            assert r.source == "hybrid"

    def test_multi_source_fusion(self):
        ranker = RRFRanker(k=60)
        query = SearchQuery(text="test")
        # key_a appears in both sources → should fuse to higher score
        results = [
            _result("key_a", score=0.9, source="keyword"),
            _result("key_b", score=0.8, source="keyword"),
            _result("key_a", score=0.85, source="semantic"),
            _result("key_c", score=0.7, source="semantic"),
        ]
        ranked = ranker.rank(results, query)
        keys = [r.memory.key for r in ranked]
        # key_a appears in both sources so its fused RRF score should be highest
        assert keys[0] == "key_a"

    def test_importance_weight_applied(self):
        ranker = RRFRanker(k=60)
        query = SearchQuery(text="test", importance_weight=1.0)
        results = [
            _result("key_low", score=0.9, source="keyword", importance=0.1),
            _result("key_high", score=0.5, source="keyword", importance=0.9),
        ]
        ranked = ranker.rank(results, query)
        # key_high has high importance so importance_weight should boost it
        assert ranked[0].memory.key == "key_high"

    def test_recency_weight_boosts_recent_memory(self):
        ranker = RRFRanker(k=60)
        query = SearchQuery(text="test", recency_weight=10.0)
        recent = datetime.now(UTC)
        old = datetime.now(UTC) - timedelta(days=365)
        results = [
            SearchResult(memory=_mem("old_key", created_at=old), score=0.8, source="keyword"),
            SearchResult(memory=_mem("new_key", created_at=recent), score=0.5, source="keyword"),
        ]
        ranked = ranker.rank(results, query)
        # The newer memory should be ranked first due to high recency weight
        assert ranked[0].memory.key == "new_key"

    def test_recency_weight_with_naive_datetime(self):
        """Memory created_at without tzinfo should be handled gracefully."""
        ranker = RRFRanker(k=60)
        query = SearchQuery(text="test", recency_weight=1.0)
        naive_dt = datetime(2024, 1, 1, 12, 0, 0)  # no tzinfo
        results = [
            SearchResult(memory=_mem("key_naive", created_at=naive_dt), score=0.5, source="keyword"),
        ]
        ranked = ranker.rank(results, query)
        assert len(ranked) == 1


# ---------------------------------------------------------------------------
# ForgettingCurveRanker
# ---------------------------------------------------------------------------


class TestForgettingCurveRanker:
    def test_empty_strength_is_passthrough(self):
        ranker = ForgettingCurveRanker(strength_lookup=lambda k: None)
        query = SearchQuery(text="test")
        results = [_result("key_a", score=0.8), _result("key_b", score=0.5)]
        # No strengths → returned unchanged
        ranked = ranker.rank(results, query)
        assert len(ranked) == 2
        assert ranked[0].score == pytest.approx(0.8)
        assert ranked[1].score == pytest.approx(0.5)

    def test_strength_adjusts_scores(self):
        # stability=0 → falls back to strength multiplier
        def lookup(k: str) -> tuple[float, float] | None:
            return {"key_a": (1.0, 0.0), "key_b": (0.2, 0.0)}.get(k)

        ranker = ForgettingCurveRanker(strength_lookup=lookup)
        query = SearchQuery(text="test")
        results = [
            _result("key_a", score=0.5),
            _result("key_b", score=0.8),
        ]
        ranked = ranker.rank(results, query)
        # key_a: 0.5 * max(0.1, 1.0) = 0.5, key_b: 0.8 * max(0.1, 0.2) = 0.16
        assert ranked[0].memory.key == "key_a"
        assert abs(ranked[0].score - 0.5) < 1e-6
        assert abs(ranked[1].score - 0.16) < 1e-6

    def test_missing_key_is_passthrough(self):
        def lookup(k: str) -> tuple[float, float] | None:
            return (0.5, 0.0) if k == "key_a" else None

        ranker = ForgettingCurveRanker(strength_lookup=lookup)
        query = SearchQuery(text="test")
        results = [
            _result("key_a", score=0.8),
            _result("key_b", score=0.6),  # not in lookup → passthrough
        ]
        ranked = ranker.rank(results, query)
        # key_a: 0.8 * max(0.1, 0.5) = 0.4, key_b: 0.6 (unchanged) → key_b wins
        assert ranked[0].memory.key == "key_b"

    def test_sorted_descending(self):
        def lookup(k: str) -> tuple[float, float] | None:
            return {"k1": (0.3, 0.0), "k2": (0.9, 0.0), "k3": (0.6, 0.0)}.get(k)

        ranker = ForgettingCurveRanker(strength_lookup=lookup)
        query = SearchQuery(text="test")
        results = [_result("k1", score=1.0), _result("k2", score=1.0), _result("k3", score=1.0)]
        ranked = ranker.rank(results, query)
        scores = [r.score for r in ranked]
        assert scores == sorted(scores, reverse=True)

    def test_source_preserved(self):
        ranker = ForgettingCurveRanker(strength_lookup=lambda k: (0.8, 0.0))
        query = SearchQuery(text="test")
        results = [_result("key_x", score=0.5, source="semantic")]
        ranked = ranker.rank(results, query)
        assert ranked[0].source == "semantic"


# ---------------------------------------------------------------------------
# SearchEngine
# ---------------------------------------------------------------------------


def _make_keyword_strategy(pairs: list[tuple[Memory, float]] | None = None, ok: bool = True):
    strat = MagicMock()
    if ok:
        strat.search.return_value = Success(pairs or [])
    else:
        from nous.domain.shared.errors import SearchError

        strat.search.return_value = Failure(SearchError("keyword error"))
    return strat


def _make_semantic_strategy(pairs: list[tuple[Memory, float]] | None = None, ok: bool = True):
    strat = AsyncMock()
    if ok:
        strat.search.return_value = Success(pairs or [])
    else:
        from nous.domain.shared.errors import SearchError

        strat.search.return_value = Failure(SearchError("semantic error"))
    return strat


class TestSearchEngineSearch:
    @pytest.mark.asyncio
    async def test_keyword_mode(self):
        mem = _mem("k1", content="hello")
        kw = _make_keyword_strategy([(mem, 0.7)])
        engine = SearchEngine(keyword_search=kw)
        result = await engine.search(SearchQuery(text="hello", mode="keyword"))
        assert result.is_ok
        assert len(result.value) == 1
        assert result.value[0].source == "keyword"
        kw.search.assert_called_once_with("hello", limit=5, date_from=None, date_to=None, tags=None)

    @pytest.mark.asyncio
    async def test_semantic_mode(self):
        mem = _mem("k2", content="hello")
        sem = _make_semantic_strategy([(mem, 0.9)])
        kw = _make_keyword_strategy()
        engine = SearchEngine(keyword_search=kw, semantic_search=sem)
        result = await engine.search(SearchQuery(text="hello", mode="semantic"))
        assert result.is_ok
        assert len(result.value) == 1
        assert result.value[0].source == "semantic"

    @pytest.mark.asyncio
    async def test_semantic_mode_without_vector_store_falls_back_to_keyword(self):
        kw = _make_keyword_strategy([(_mem("kw1"), 0.8)])
        engine = SearchEngine(keyword_search=kw, semantic_search=None)
        result = await engine.search(SearchQuery(text="hello", mode="semantic"))
        assert result.is_ok
        assert len(result.value) == 1
        assert result.value[0].memory.key == "kw1"

    @pytest.mark.asyncio
    async def test_hybrid_mode_combines_results(self):
        mem_kw = _mem("kw_key")
        mem_sem = _mem("sem_key")
        kw = _make_keyword_strategy([(mem_kw, 0.7)])
        sem = _make_semantic_strategy([(mem_sem, 0.8)])
        engine = SearchEngine(keyword_search=kw, semantic_search=sem)
        result = await engine.search(SearchQuery(text="hello", mode="hybrid", top_k=10))
        assert result.is_ok
        keys = {r.memory.key for r in result.value}
        assert "kw_key" in keys
        assert "sem_key" in keys

    @pytest.mark.asyncio
    async def test_hybrid_mode_deduplicates(self):
        mem = _mem("shared_key")
        kw = _make_keyword_strategy([(mem, 0.7)])
        sem = _make_semantic_strategy([(mem, 0.9)])
        engine = SearchEngine(keyword_search=kw, semantic_search=sem)
        result = await engine.search(SearchQuery(text="hello", mode="hybrid", top_k=10))
        assert result.is_ok
        assert sum(1 for r in result.value if r.memory.key == "shared_key") == 1

    @pytest.mark.asyncio
    async def test_unknown_mode_falls_back_to_hybrid(self):
        mem_kw = _mem("kw_key")
        kw = _make_keyword_strategy([(mem_kw, 0.5)])
        sem = _make_semantic_strategy()
        engine = SearchEngine(keyword_search=kw, semantic_search=sem)
        result = await engine.search(SearchQuery(text="hello", mode="bogus_mode"))
        assert result.is_ok

    @pytest.mark.asyncio
    async def test_smart_mode_falls_back_to_hybrid(self):
        mem_kw = _mem("kw_key")
        kw = _make_keyword_strategy([(mem_kw, 0.5)])
        engine = SearchEngine(keyword_search=kw)
        result = await engine.search(SearchQuery(text="hello", mode="smart"))
        assert result.is_ok

    @pytest.mark.asyncio
    async def test_hybrid_empty_results(self):
        kw = _make_keyword_strategy([])
        sem = _make_semantic_strategy([])
        engine = SearchEngine(keyword_search=kw, semantic_search=sem)
        result = await engine.search(SearchQuery(text="hello", mode="hybrid"))
        assert result.is_ok
        assert result.value == []

    @pytest.mark.asyncio
    async def test_hybrid_uses_ranker_when_provided(self):
        mem_kw = _mem("k1")
        mem_sem = _mem("k2")
        kw = _make_keyword_strategy([(mem_kw, 0.5)])
        sem = _make_semantic_strategy([(mem_sem, 0.8)])
        ranker = MagicMock()
        combined = [
            SearchResult(memory=mem_sem, score=0.9, source="semantic"),
            SearchResult(memory=mem_kw, score=0.5, source="keyword"),
        ]
        ranker.rank.return_value = combined
        engine = SearchEngine(keyword_search=kw, semantic_search=sem, ranker=ranker)
        result = await engine.search(SearchQuery(text="hello", mode="hybrid"))
        assert result.is_ok
        ranker.rank.assert_called_once()

    @pytest.mark.asyncio
    async def test_keyword_failure_propagates(self):
        kw = _make_keyword_strategy(ok=False)
        engine = SearchEngine(keyword_search=kw)
        result = await engine.search(SearchQuery(text="hello", mode="keyword"))
        assert not result.is_ok

    @pytest.mark.asyncio
    async def test_top_k_limits_hybrid_results(self):
        mems = [_mem(f"key_{i}") for i in range(10)]
        pairs = [(m, float(i) / 10) for i, m in enumerate(mems)]
        kw = _make_keyword_strategy(pairs)
        engine = SearchEngine(keyword_search=kw)
        result = await engine.search(SearchQuery(text="test", mode="hybrid", top_k=3))
        assert result.is_ok
        assert len(result.value) <= 3


class TestQueryCache:
    """Module-level query cache: hit, shallow copy, TTL expiry, exclusions."""

    @pytest.mark.asyncio
    async def test_second_query_hits_cache(self):
        """Same query twice → strategies called once, results identical."""
        mem = _mem("k1", content="cached content")
        kw = _make_keyword_strategy([(mem, 0.7)])
        engine = SearchEngine(keyword_search=kw)
        q = SearchQuery(text="cache me", mode="hybrid", top_k=5)

        r1 = await engine.search(q)
        r2 = await engine.search(q)

        assert r1.is_ok and r2.is_ok
        assert [x.memory.key for x in r1.value] == [x.memory.key for x in r2.value]
        assert kw.search.call_count == 1, "second identical query should hit the cache"

    @pytest.mark.asyncio
    async def test_cache_returns_shallow_copy(self):
        """Mutating the returned list must not corrupt the cached entry."""
        mem = _mem("k1", content="copy me")
        kw = _make_keyword_strategy([(mem, 0.7)])
        engine = SearchEngine(keyword_search=kw)
        q = SearchQuery(text="copy query", mode="hybrid", top_k=5)

        r1 = await engine.search(q)
        r1.value.append(SearchResult(memory=_mem("k2"), score=9.9, source="semantic"))

        r2 = await engine.search(q)
        assert len(r2.value) == 1
        assert r2.value[0].memory.key == "k1"

    @pytest.mark.asyncio
    async def test_cache_expires_after_ttl(self):
        """Aged cache entries are dropped and the query re-executes."""
        from nous.domain.search.engine import _query_cache

        mem = _mem("k1", content="ttl")
        kw = _make_keyword_strategy([(mem, 0.7)])
        engine = SearchEngine(keyword_search=kw)
        q = SearchQuery(text="ttl query", mode="hybrid", top_k=5)

        await engine.search(q)
        assert kw.search.call_count == 1

        key = engine._query_cache_key(q, "hybrid")
        assert key is not None and key in _query_cache
        ts, results = _query_cache[key]
        _query_cache[key] = (ts - 31.0, results)  # age past the 30s TTL

        r2 = await engine.search(q)
        assert r2.is_ok and len(r2.value) == 1
        assert kw.search.call_count == 2, "expired entry should re-execute the query"

    @pytest.mark.asyncio
    async def test_keyword_mode_not_cached(self):
        """keyword mode bypasses the cache (strategy called every time)."""
        mem = _mem("k1")
        kw = _make_keyword_strategy([(mem, 0.7)])
        engine = SearchEngine(keyword_search=kw)
        q = SearchQuery(text="hello", mode="keyword")

        await engine.search(q)
        await engine.search(q)
        assert kw.search.call_count == 2

    @pytest.mark.asyncio
    async def test_empty_text_not_cached(self):
        """Empty-text (tag-only) queries bypass the cache."""
        mem = _mem("k1", tags=["work"])
        kw = _make_keyword_strategy([(mem, 0.7)])
        engine = SearchEngine(keyword_search=kw)
        q = SearchQuery(text="   ", mode="hybrid", tags=["work"])

        await engine.search(q)
        await engine.search(q)
        assert kw.search.call_count == 2

    @pytest.mark.asyncio
    async def test_filters_applied_outside_cache(self):
        """emotion/kind/tags filters still apply on cache hits."""
        mem = _mem("k1", content="moody", emotion="happy")
        kw = _make_keyword_strategy([(mem, 0.7)])
        engine = SearchEngine(keyword_search=kw)
        q = SearchQuery(text="mood query", mode="hybrid", top_k=5)

        r1 = await engine.search(q)
        assert len(r1.value) == 1
        r2 = await engine.search(SearchQuery(text="mood query", mode="hybrid", top_k=5, emotion="sad"))
        assert r2.is_ok
        assert r2.value == [], "emotion filter must be applied on every request"

    @pytest.mark.asyncio
    async def test_engines_do_not_share_cache(self):
        """Two engines with different repos (e.g. different personas) must not share results."""
        mem = _mem("k1", content="isolation")
        kw = _make_keyword_strategy([(mem, 0.7)])
        engine_a = SearchEngine(keyword_search=kw, memory_repo=object())
        engine_b = SearchEngine(keyword_search=kw, memory_repo=object())
        q = SearchQuery(text="isolated query", mode="hybrid", top_k=5)

        await engine_a.search(q)
        await engine_b.search(q)

        assert kw.search.call_count == 2, "each engine must execute its own query"


class TestSearchEngineFilterByEmotion:
    def test_no_emotion_filter_returns_all(self):
        results = [
            _result("k1", score=1.0, emotion="joy"),
            _result("k2", score=0.9, emotion="sadness"),
        ]
        out = SearchEngine._filter_by_emotion(results, None)
        assert out == results

    def test_matching_emotion_kept(self):
        results = [
            _result("k1", score=1.0, emotion="joy"),
            _result("k2", score=0.9, emotion="sadness"),
        ]
        out = SearchEngine._filter_by_emotion(results, "joy")
        assert len(out) == 1
        assert out[0].memory.key == "k1"

    def test_no_match_returns_empty(self):
        results = [_result("k1", score=1.0, emotion="sadness")]
        out = SearchEngine._filter_by_emotion(results, "joy")
        assert out == []

    def test_emotion_normalization(self):
        """normalize_emotion should allow keyword synonyms to match."""
        results = [_result("k1", score=1.0, emotion="happy")]
        # "joy" and "happy" normalize to the same canonical value
        out = SearchEngine._filter_by_emotion(results, "joy")
        assert len(out) == 1


# ---------------------------------------------------------------------------
# SearchEngine sort by updated_at (V9)
# ---------------------------------------------------------------------------


class TestSearchEngineSortByUpdatedAt:
    """V9: sort="updated_at" で更新日時降順（最新優先）ソート。"""

    @pytest.mark.asyncio
    async def test_sort_updated_at_descending(self):
        """updated_at 降順（最新が先頭）になること。"""
        base = datetime.now(UTC)
        kw = _make_keyword_strategy(
            [
                (_mem("old", created_at=base - timedelta(days=10), updated_at=base - timedelta(days=10)), 0.9),
                (_mem("mid", created_at=base - timedelta(days=5), updated_at=base - timedelta(days=5)), 0.5),
                (_mem("new", created_at=base, updated_at=base), 0.1),
            ]
        )
        engine = SearchEngine(keyword_search=kw)
        result = await engine.search(SearchQuery(text="", mode="hybrid", top_k=10, sort="updated_at"))
        assert result.is_ok
        assert [r.memory.key for r in result.value] == ["new", "mid", "old"]

    @pytest.mark.asyncio
    async def test_empty_query_with_tags_sorts_by_updated_at_and_respects_top_k(self):
        """空クエリ + tags + sort=updated_at で updated_at 降順 & top_k 制限が効くこと。"""
        base = datetime.now(UTC)
        memory_repo = MagicMock()
        memory_repo.get_by_tags.return_value = Success(
            [
                _mem("old", updated_at=base - timedelta(hours=3), tags=["project:nous"]),
                _mem("mid", updated_at=base - timedelta(hours=2), tags=["project:nous"]),
                _mem("new", updated_at=base - timedelta(hours=1), tags=["project:nous"]),
            ]
        )
        engine = SearchEngine(keyword_search=_make_keyword_strategy(), memory_repo=memory_repo)
        result = await engine.search(
            SearchQuery(text="", mode="hybrid", top_k=2, tags=["project:nous"], sort="updated_at")
        )
        assert result.is_ok
        assert [r.memory.key for r in result.value] == ["new", "mid"]
        memory_repo.get_by_tags.assert_called_once_with(["project:nous"])

    @pytest.mark.asyncio
    async def test_sort_none_keeps_score_order(self):
        """sort=None（従来動作）ではスコア降順のまま。"""
        base = datetime.now(UTC)
        kw = _make_keyword_strategy(
            [
                (_mem("new", created_at=base, updated_at=base), 0.1),
                (_mem("old", created_at=base - timedelta(days=10), updated_at=base - timedelta(days=10)), 0.9),
            ]
        )
        engine = SearchEngine(keyword_search=kw)
        result = await engine.search(SearchQuery(text="", mode="hybrid", top_k=10))
        assert result.is_ok
        assert [r.memory.key for r in result.value] == ["old", "new"]  # score order preserved


# ---------------------------------------------------------------------------
# SearchEngine date_range integration tests (P1)
# ---------------------------------------------------------------------------


class TestSearchEngineDateRange:
    """P1: date_range パラメータが検索戦略に正しく伝播されることを確認。"""

    def _make_kw(self, pairs=None):
        strat = MagicMock()
        strat.search.return_value = Success(pairs or [])
        return strat

    @pytest.mark.asyncio
    async def test_date_range_none_passes_none(self):
        """date_range未指定時は date_from/date_to に None が渡される。"""
        kw = self._make_kw()
        engine = SearchEngine(keyword_search=kw)
        result = await engine.search(SearchQuery(text="hello", mode="keyword"))
        assert result.is_ok
        kw.search.assert_called_once_with("hello", limit=5, date_from=None, date_to=None, tags=None)

    @pytest.mark.asyncio
    async def test_date_range_passes_parsed_dates_to_keyword(self):
        """date_range指定時はパース結果がキーワード検索に渡される。"""
        kw = self._make_kw()
        engine = SearchEngine(keyword_search=kw)
        result = await engine.search(SearchQuery(text="hello", mode="keyword", date_range="7d"))
        assert result.is_ok
        call_args = kw.search.call_args
        assert call_args.kwargs["date_from"] is not None
        assert call_args.kwargs["date_to"] is not None

    @pytest.mark.asyncio
    async def test_date_range_passes_parsed_dates_to_semantic(self):
        """date_range指定時はパース結果がセマンティック検索に渡される。"""
        sem = _make_semantic_strategy()
        kw = self._make_kw()
        engine = SearchEngine(keyword_search=kw, semantic_search=sem)
        result = await engine.search(SearchQuery(text="hello", mode="semantic", date_range="昨日"))
        assert result.is_ok
        call_args = sem.search.call_args
        assert call_args.kwargs["date_from"] is not None
        assert call_args.kwargs["date_to"] is not None

    @pytest.mark.asyncio
    async def test_date_range_passes_to_hybrid_both_strategies(self):
        """ハイブリッドモードで両方の戦略に date_range が渡される。"""
        sem = _make_semantic_strategy()
        kw = self._make_kw()
        engine = SearchEngine(keyword_search=kw, semantic_search=sem)
        result = await engine.search(SearchQuery(text="hello", mode="hybrid", date_range="30d"))
        assert result.is_ok
        # keyword strategy should receive parsed dates
        assert kw.search.call_args.kwargs["date_from"] is not None
        assert sem.search.call_args.kwargs["date_to"] is not None

    @pytest.mark.asyncio
    async def test_date_range_invalid_string_passes_none(self):
        """パースできない文字列は None,None として扱われる（フィルタなし＝全件）。"""
        kw = self._make_kw()
        engine = SearchEngine(keyword_search=kw)
        result = await engine.search(SearchQuery(text="hello", mode="keyword", date_range="わけわからん"))
        assert result.is_ok
        kw.search.assert_called_once_with("hello", limit=5, date_from=None, date_to=None, tags=None)

    @pytest.mark.asyncio
    async def test_date_range_empty_string_passes_none(self):
        """空文字列は None,None として扱われる。"""
        kw = self._make_kw()
        engine = SearchEngine(keyword_search=kw)
        result = await engine.search(SearchQuery(text="hello", mode="keyword", date_range=""))
        assert result.is_ok
        kw.search.assert_called_once_with("hello", limit=5, date_from=None, date_to=None, tags=None)


# ---------------------------------------------------------------------------
# SearchEngine tags filter (bugfix: tags were never passed to strategies)
# ---------------------------------------------------------------------------


class TestSearchEngineTags:
    """tags パラメータが検索戦略へ伝播し、タグ絞り込みが機能すること。"""

    @pytest.mark.asyncio
    async def test_keyword_mode_passes_tags_to_strategy(self):
        """keyword モードで tags が戦略に渡される。"""
        kw = _make_keyword_strategy([(_mem("k1", content="hello", tags=["project:nous"]), 0.7)])
        engine = SearchEngine(keyword_search=kw)
        result = await engine.search(SearchQuery(text="hello", mode="keyword", tags=["project:nous"]))
        assert result.is_ok
        assert len(result.value) == 1
        kw.search.assert_called_once_with("hello", limit=5, date_from=None, date_to=None, tags=["project:nous"])

    @pytest.mark.asyncio
    async def test_hybrid_mode_passes_tags_to_keyword_and_fts(self):
        """hybrid モードで tags が keyword 戦略と search_fts に渡される。"""
        kw = _make_keyword_strategy([(_mem("k1"), 0.7)])
        sem = _make_semantic_strategy([])
        memory_repo = MagicMock()
        memory_repo.search_fts.return_value = Success([])
        engine = SearchEngine(keyword_search=kw, semantic_search=sem, memory_repo=memory_repo)
        result = await engine.search(SearchQuery(text="hello", mode="hybrid", tags=["project:nous", "task_state"]))
        assert result.is_ok
        assert kw.search.call_args.kwargs["tags"] == ["project:nous", "task_state"]
        assert memory_repo.search_fts.call_args.kwargs["tags"] == ["project:nous", "task_state"]

    @pytest.mark.asyncio
    async def test_empty_query_with_tags_uses_get_by_tags_keyword_mode(self):
        """空クエリ + tags 指定で get_by_tags フォールバックが動く（keyword モード）。"""
        mem = _mem("k1", content="hello", tags=["project:nous"])
        memory_repo = MagicMock()
        memory_repo.get_by_tags.return_value = Success([mem])
        engine = SearchEngine(keyword_search=_make_keyword_strategy(), memory_repo=memory_repo)
        result = await engine.search(SearchQuery(text="", mode="keyword", tags=["project:nous"]))
        assert result.is_ok
        assert len(result.value) == 1
        assert result.value[0].memory.key == "k1"
        assert result.value[0].source == "keyword"
        memory_repo.get_by_tags.assert_called_once_with(["project:nous"])

    @pytest.mark.asyncio
    async def test_empty_query_with_tags_uses_get_by_tags_hybrid_mode(self):
        """空クエリ + tags 指定で get_by_tags フォールバックが動く（hybrid モード）。"""
        mem = _mem("k1", content="hello", tags=["project:nous"])
        memory_repo = MagicMock()
        memory_repo.get_by_tags.return_value = Success([mem])
        engine = SearchEngine(keyword_search=_make_keyword_strategy(), memory_repo=memory_repo)
        result = await engine.search(SearchQuery(text="", mode="hybrid", tags=["project:nous"]))
        assert result.is_ok
        assert len(result.value) == 1
        assert result.value[0].memory.key == "k1"
        memory_repo.get_by_tags.assert_called_once_with(["project:nous"])


class TestFilterByTags:
    def test_none_tags_returns_all(self) -> None:
        results = [_result("k1", 1.0)]
        out = SearchEngine._filter_by_tags(results, None)
        assert out == results

    def test_keeps_only_memories_with_all_tags(self) -> None:
        results = [
            _result("k1", 1.0, tags=["a", "b"]),
            _result("k2", 0.9, tags=["a"]),
            _result("k3", 0.8, tags=["b", "c"]),
        ]
        out = SearchEngine._filter_by_tags(results, ["a", "b"])
        assert [r.memory.key for r in out] == ["k1"]

    def test_no_match_returns_empty(self) -> None:
        results = [_result("k1", 1.0, tags=["c"])]
        out = SearchEngine._filter_by_tags(results, ["a"])
        assert out == []

    @pytest.mark.asyncio
    async def test_search_applies_tag_post_filter_to_semantic_noise(self) -> None:
        """semantic 経路の結果にタグが含まれないものは除外される。"""
        tagged = _mem("tagged", tags=["project:nous"])
        noise = _mem("noise", tags=["other"])
        sem = _make_semantic_strategy([(tagged, 0.9), (noise, 0.8)])
        kw = _make_keyword_strategy([])
        engine = SearchEngine(keyword_search=kw, semantic_search=sem)
        result = await engine.search(SearchQuery(text="hello", mode="hybrid", tags=["project:nous"]))
        assert result.is_ok
        assert [r.memory.key for r in result.value] == ["tagged"]


def _make_memory(key: str):
    m = MagicMock()
    m.key = key
    m.content = f"content of {key}"
    m.emotion = None
    return m


def _make_engine(memorag_config=None, memory_repo=None):
    keyword = MagicMock()
    keyword.search.return_value = Success([(_make_memory("k1"), 0.9)])
    semantic = AsyncMock()
    semantic.search.return_value = Success([(_make_memory("k2"), 0.8)])
    return SearchEngine(keyword, semantic, None, memory_repo=memory_repo, memorag_config=memorag_config)


class TestBestSearchMode:
    def test_hybrid_when_disabled(self):
        config = MagicMock()
        config.enabled = False
        engine = _make_engine(memorag_config=config)
        assert engine.best_search_mode() == "hybrid"

    def test_smart_when_enabled(self):
        config = MagicMock()
        config.enabled = True
        engine = _make_engine(memorag_config=config)
        assert engine.best_search_mode() == "smart"
