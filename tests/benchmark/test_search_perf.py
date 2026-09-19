"""Performance benchmarks for search operations."""

import asyncio
from datetime import UTC, datetime
from unittest.mock import MagicMock

import numpy as np

from nous.domain.memory.entities import Memory, MemoryStrength
from nous.domain.search.engine import SearchEngine, SearchQuery, SearchResult
from nous.domain.search.policy import RankPolicy
from nous.domain.search.ranker import ForgettingCurveRanker, RRFRanker
from nous.domain.shared.result import Success


def make_memories(n: int) -> list[Memory]:
    return [
        Memory(
            key=f"mem_{i:04d}",
            content=f"テスト記憶 {i}: ユーザーは Python が好きで機械学習に興味がある",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            importance=0.5 + (i % 5) * 0.1,
            emotion="neutral",
            tags=["test"],
        )
        for i in range(n)
    ]


def test_rrf_ranker_100(benchmark):
    """Benchmark RRF ranking with 100 results."""
    ranker = RRFRanker()
    memories = make_memories(100)
    results = [SearchResult(m, score=0.9 - i * 0.001, source="keyword") for i, m in enumerate(memories)]
    query = SearchQuery(text="Python 機械学習", top_k=10)
    benchmark(ranker.rank, results, query)


def test_rrf_ranker_1000(benchmark):
    """Benchmark RRF ranking with 1000 results."""
    ranker = RRFRanker()
    memories = make_memories(1000)
    results = [SearchResult(memories[i], score=0.9 - i * 0.0001, source="keyword") for i in range(1000)]
    query = SearchQuery(text="Python 機械学習", top_k=10)
    benchmark(ranker.rank, results, query)


def test_forgetting_ranker_100(benchmark):
    """Benchmark ForgettingCurveRanker with 100 results."""
    memories = make_memories(100)

    def strengths(key: str) -> tuple[float, float] | None:
        return (0.5 + (int(key.split("_")[1]) % 10) * 0.05, 0.0)

    ranker = ForgettingCurveRanker(strength_lookup=strengths)
    results = [SearchResult(m, score=0.9, source="hybrid") for m in memories]
    query = SearchQuery(text="test", top_k=10)
    benchmark(ranker.rank, results, query)


def test_memory_entity_creation_batch(benchmark):
    """Benchmark creating 100 Memory entities."""
    benchmark(make_memories, 100)


def test_fsrs_compute_recall(benchmark):
    """Benchmark FSRS power-law recall computation."""
    ms = MemoryStrength(memory_key="test", strength=0.8, stability=7.0)
    benchmark(ms.compute_recall, 24.0)


class _FakeEncoder:
    """ContentEncoder 構造互換の固定ベクトル返却スタブ（policy 段の計測用）。"""

    async def async_encode_batch(self, texts: list[str], *, is_query: bool = False) -> np.ndarray:
        return np.full((len(texts), 8), 0.125, dtype=np.float64)


def _policy_engine(semantic_pair_count: int) -> tuple[SearchEngine, SearchQuery, list[SearchResult]]:
    """rank_policy 段の計測対象: 候補を keyword 戦略が返し、policy で再順位付けする。"""
    memories = make_memories(semantic_pair_count)
    pairs = [(m, 0.9 - i * 0.001) for i, m in enumerate(memories)]
    strat = MagicMock()
    strat.search.return_value = Success(pairs)
    engine = SearchEngine(keyword_search=strat, embedding_provider=lambda: _FakeEncoder())
    results = [SearchResult(m, score=0.9 - i * 0.001, source="hybrid") for i, m in enumerate(memories)]
    query = SearchQuery(text="Python 機械学習", top_k=10, rank_policy=RankPolicy())
    return engine, query, results


def test_rank_policy_finalize_100(benchmark):
    """Benchmark the RankPolicy final stage (post-filter → composite → truncate) with 100 candidates."""
    engine, query, results = _policy_engine(100)

    def _run() -> list[SearchResult]:
        return asyncio.run(engine._finalize(results, query))

    out = benchmark(_run)
    assert len(out) == query.top_k


def test_rank_policy_full_search_1000(benchmark):
    """Benchmark full policy search (fetch 1000 → finalize) via engine.search().

    cache ミス以降は cache hit 経路（strategy を once だけ呼ぶ）を計測する。
    """
    engine, query, _ = _policy_engine(1000)

    def _run() -> None:
        asyncio.run(engine.search(query))

    benchmark(_run)
    assert engine._keyword.search.call_count == 1, "cache hit path should be benchmarked"
