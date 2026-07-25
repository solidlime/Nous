"""Performance benchmarks for search operations."""

from datetime import UTC, datetime

from nous.domain.memory.entities import Memory, MemoryStrength
from nous.domain.search.engine import SearchQuery, SearchResult
from nous.domain.search.ranker import ForgettingCurveRanker, RRFRanker


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
