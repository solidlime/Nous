from __future__ import annotations

from unittest.mock import MagicMock

from nous.domain.search.engine import SearchQuery, SearchResult
from nous.domain.search.ranker import ChainedRanker


def _make_result(key: str, score: float, source: str = "keyword") -> SearchResult:
    memory = MagicMock()
    memory.key = key
    memory.importance = 0.5
    memory.created_at = None
    memory.emotion = None
    return SearchResult(memory=memory, score=score, source=source)


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
