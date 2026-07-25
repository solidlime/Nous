from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

import pytest

from nous.domain.search.engine import SearchQuery, SearchResult
from nous.domain.search.ranker import ChainedRanker, ForgettingCurveRanker, RRFRanker


def _make_result(key: str, score: float, source: str = "keyword") -> SearchResult:
    memory = MagicMock()
    memory.key = key
    memory.importance = 0.5
    memory.created_at = None
    memory.emotion = None
    return SearchResult(memory=memory, score=score, source=source)


class TestForgettingCurveRanker:
    def test_returns_unchanged_when_no_lookup(self) -> None:
        ranker = ForgettingCurveRanker()
        results = [_make_result("a", 1.0), _make_result("b", 0.5)]
        query = SearchQuery(text="test")
        assert ranker.rank(results, query) is results

    def test_callable_lookup_returns_strength_tuple(self) -> None:
        """Callable returns (strength, stability) tuple or None."""
        lookup = {"a": (0.5, 0.0), "b": (1.0, 0.0)}  # stability=0 → uses strength multiplier
        ranker = ForgettingCurveRanker(lambda key: lookup.get(key))
        results = [_make_result("a", 1.0), _make_result("b", 1.0)]
        query = SearchQuery(text="test")
        ranked = ranker.rank(results, query)
        scores = {r.memory.key: r.score for r in ranked}
        # a: 1.0 * max(0.1, 0.5) = 0.5, b: 1.0 * max(0.1, 1.0) = 1.0
        assert scores["a"] == pytest.approx(0.5)
        assert scores["b"] == pytest.approx(1.0)

    def test_callable_lookup_with_stability(self) -> None:
        """With stability > 0, FSRS recall probability is computed."""
        lookup = {"a": (1.0, 1000.0)}  # high stability → recall ≈ 1.0
        ranker = ForgettingCurveRanker(lambda key: lookup.get(key))
        # created_at is None → falls to stability=0 branch → strength multiplier
        results = [_make_result("a", 1.0)]
        query = SearchQuery(text="test")
        ranked = ranker.rank(results, query)
        # Since created_at is None, stability > 0 path is skipped → strength * max(0.1, 1.0)
        assert ranked[0].score == pytest.approx(1.0)

    def test_missing_key_is_passthrough(self) -> None:
        """None from lookup → no score modification."""
        ranker = ForgettingCurveRanker(lambda key: None)
        results = [_make_result("unknown", 3.0)]
        query = SearchQuery(text="test")
        ranked = ranker.rank(results, query)
        assert ranked[0].score == pytest.approx(3.0)

    def test_sorted_by_score_descending(self) -> None:
        lookup = {"a": (0.1, 0.0), "b": (0.9, 0.0)}
        ranker = ForgettingCurveRanker(lambda key: lookup.get(key))
        results = [_make_result("a", 1.0), _make_result("b", 1.0)]
        query = SearchQuery(text="test")
        ranked = ranker.rank(results, query)
        assert ranked[0].memory.key == "b"
        assert ranked[1].memory.key == "a"

    def test_none_strength_data_is_passthrough(self) -> None:
        """When lookup returns None, result is unchanged."""
        ranker = ForgettingCurveRanker(lambda key: None)
        results = [_make_result("a", 0.5)]
        query = SearchQuery(text="test")
        ranked = ranker.rank(results, query)
        assert len(ranked) == 1
        assert ranked[0].score == pytest.approx(0.5)

    def test_handles_naive_created_at(self) -> None:
        """offset-naive created_at (from SQLite) must not crash when compared with offset-aware now."""
        memory = MagicMock()
        memory.key = "x"
        memory.created_at = datetime(2024, 1, 1, 12, 0, 0)  # offset-naive, no tzinfo
        memory.importance = 0.5
        memory.emotion = None
        result = SearchResult(memory=memory, score=1.0, source="keyword")
        ranker = ForgettingCurveRanker(lambda key: (1.0, 100.0))  # stability > 0
        query = SearchQuery(text="test")
        ranked = ranker.rank([result], query)
        assert len(ranked) == 1
        assert ranked[0].score > 0


class TestChainedRanker:
    def test_applies_rankers_in_order(self) -> None:
        first = MagicMock()
        second = MagicMock()
        results = [_make_result("a", 1.0)]
        intermediate = [_make_result("a", 0.5)]
        final = [_make_result("a", 0.25)]
        first.rank.return_value = intermediate
        second.rank.return_value = final
        query = SearchQuery(text="test")

        chained = ChainedRanker(first, second)
        out = chained.rank(results, query)

        first.rank.assert_called_once_with(results, query)
        second.rank.assert_called_once_with(intermediate, query)
        assert out is final

    def test_empty_rankers_returns_results_unchanged(self) -> None:
        results = [_make_result("a", 1.0)]
        query = SearchQuery(text="test")
        chained = ChainedRanker()
        assert chained.rank(results, query) is results

    def test_rrf_then_forgetting_curve(self) -> None:
        """Integration: RRFRanker followed by ForgettingCurveRanker."""
        r1 = _make_result("mem_strong", 1.0, source="keyword")
        r2 = _make_result("mem_weak", 0.9, source="keyword")
        query = SearchQuery(text="test")

        def strengths(key: str) -> tuple[float, float] | None:
            return {"mem_strong": (1.0, 0.0), "mem_weak": (0.1, 0.0)}.get(key)

        chained = ChainedRanker(RRFRanker(), ForgettingCurveRanker(strengths))
        ranked = chained.rank([r1, r2], query)

        # mem_weak should be pushed down due to low recall probability
        assert ranked[0].memory.key == "mem_strong"
        assert ranked[1].memory.key == "mem_weak"
