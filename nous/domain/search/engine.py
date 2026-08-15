from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from nous.domain.shared.result import Failure, Result, Success
from nous.domain.shared.time_utils import parse_date_range
from nous.domain.value_objects import normalize_emotion

if TYPE_CHECKING:
    from datetime import datetime

    from nous.domain.memory.entities import Memory
    from nous.domain.search.ranker import ResultRanker
    from nous.domain.search.strategies import (
        KeywordSearchStrategy,
        SemanticSearchStrategy,
    )
    from nous.domain.shared.errors import SearchError


from nous.infrastructure.logging.structured import get_logger

logger = get_logger(__name__)

# Query result cache: key -> (monotonic timestamp, results). TTL-only invalidation.
_CACHE_TTL_S = 30.0
_CACHE_MAX = 256
_query_cache: dict[tuple, tuple[float, list[SearchResult]]] = {}
_query_lock = threading.Lock()


def _cache_get(key: tuple) -> list[SearchResult] | None:
    """Return a shallow copy of cached results if fresh, else None."""
    with _query_lock:
        entry = _query_cache.get(key)
        if entry is None:
            return None
        ts, results = entry
        if time.monotonic() - ts > _CACHE_TTL_S:
            _query_cache.pop(key, None)
            return None
    return [r for r in results]


def _cache_put(key: tuple, results: list[SearchResult]) -> None:
    """Store results under key, dropping all entries when at capacity."""
    with _query_lock:
        if len(_query_cache) >= _CACHE_MAX:
            _query_cache.clear()
        _query_cache[key] = (time.monotonic(), list(results))


def invalidate_query_cache() -> None:
    """Drop all cached query results (called on memory writes via event bus)."""
    with _query_lock:
        _query_cache.clear()


@dataclass
class SearchQuery:
    """Search query parameters."""

    text: str
    mode: str = "hybrid"
    top_k: int = 5
    tags: list[str] | None = None
    date_range: str | None = None
    min_importance: float | None = None
    emotion: str | None = None
    importance_weight: float = 0.0
    recency_weight: float = 0.0
    lifecycle_status: str | None = "active"
    vector_weight: float = 1.0  # RRF weight for vector/semantic signal
    keyword_weight: float = 0.5  # RRF weight for keyword (FTS5 + plain) signal
    similarity_threshold: float = 0.85  # cosine similarity flag threshold
    valid_at: datetime | None = None  # Only return memories valid at this timestamp
    kind: str | None = None  # episodic / semantic / procedural / prospective
    sort: str | None = None  # "updated_at" 指定時は updated_at 降順


@dataclass
class SearchResult:
    """A single search result with score and source info."""

    memory: Memory
    score: float
    source: str  # "semantic" | "keyword" | "fts" | "hybrid"
    similarity_flag: bool = False  # True when cosine_similarity >= threshold


class SearchEngine:
    """Orchestrates search strategies and produces ranked results."""

    def __init__(
        self,
        keyword_search: KeywordSearchStrategy,
        semantic_search: SemanticSearchStrategy | None = None,
        ranker: ResultRanker | None = None,
        memory_repo=None,
        memorag_config=None,
        reranker=None,
        link_repo=None,
        entity_service=None,
    ) -> None:
        self._keyword = keyword_search
        self._semantic = semantic_search
        self._ranker = ranker
        self._memory_repo = memory_repo
        self._memorag_config = memorag_config
        self._reranker = reranker
        self._link_repo = link_repo
        self._entity_service = entity_service
        self._reranker_unloaded_warned = False

    def _post_filter(self, results: list[SearchResult], query: SearchQuery) -> list[SearchResult]:
        """Apply per-request filters/sort outside the query cache."""
        filtered = self._filter_by_emotion(results, query.emotion)
        filtered = self._filter_by_kind(filtered, query.kind)
        filtered = self._filter_by_tags(filtered, query.tags)
        if query.valid_at is not None:
            filtered = self._filter_by_valid_at(filtered, query.valid_at)
        if query.sort == "updated_at":
            filtered.sort(key=lambda r: r.memory.updated_at, reverse=True)
        return filtered

    def _query_cache_key(self, query: SearchQuery, mode: str) -> tuple | None:
        """Build the cache key for cacheable queries, or None to skip caching."""
        if mode not in ("hybrid", "semantic", "smart") or not query.text.strip():
            return None
        persona = self._semantic.persona if self._semantic is not None else "default"
        # Engine identity: the module-level cache is shared across engines, so
        # include per-engine state (repo) to prevent cross-engine/persona leaks.
        engine_id = id(self._memory_repo) if self._memory_repo is not None else id(self)
        return (
            engine_id,
            persona,
            query.text,
            mode,
            query.top_k,
            tuple(query.tags) if query.tags else None,
            query.date_range,
            query.min_importance,
            query.kind,
            query.importance_weight,
            query.recency_weight,
            query.vector_weight,
            query.keyword_weight,
            query.similarity_threshold,
            query.sort,
            query.lifecycle_status,
            query.valid_at,
        )

    async def search(self, query: SearchQuery) -> Result[list[SearchResult], SearchError]:
        """Execute search using the specified mode.

        Modes:
            - ``hybrid`` (default): Keyword + semantic RRF fusion. Falls back to keyword-only
              if no vector store is configured.
            - ``keyword``: SQLite keyword search only (fast, exact matches).
            - ``semantic``: Qdrant vector search only (semantic similarity).
            - ``smart``: Query expansion + multi-pass hybrid search merged with RRF.
            - Any other value: falls back to hybrid.
        """
        # Parse date_range once for all strategies
        date_from, date_to = parse_date_range(query.date_range)

        mode = query.mode or "hybrid"
        cache_key = self._query_cache_key(query, mode)
        if cache_key is not None:
            cached = _cache_get(cache_key)
            if cached is not None:
                return Success(self._post_filter(cached, query))

        if mode == "keyword":
            result = self._keyword_search(query, date_from, date_to)
        elif mode == "semantic":
            result = await self._semantic_search(query, date_from, date_to)
        elif mode == "smart":
            result = await self._smart_search(query)
        else:
            result = await self._hybrid_search(query, date_from, date_to)

        if not result.is_ok:
            return result
        # Never cache empty results: cold-start fallbacks (e.g. embedding not
        # loaded yet) would otherwise poison the cache for the full TTL.
        if cache_key is not None and result.value:
            _cache_put(cache_key, result.value)
        return Success(self._post_filter(result.value, query))

    @staticmethod
    def _filter_by_emotion(
        results: list[SearchResult],
        emotion: str | None,
    ) -> list[SearchResult]:
        """Post-filter results by emotion using normalized comparison."""
        if emotion is None:
            return results
        target = normalize_emotion(emotion)
        return [r for r in results if normalize_emotion(r.memory.emotion) == target]

    @staticmethod
    def _filter_by_kind(
        results: list[SearchResult],
        kind: str | None,
    ) -> list[SearchResult]:
        """Post-filter results by memory kind."""
        if kind is None:
            return results
        from nous.domain.memory.entities import VALID_KINDS

        if kind not in VALID_KINDS:
            return results
        return [r for r in results if r.memory.kind == kind]

    @staticmethod
    def _filter_by_tags(
        results: list[SearchResult],
        tags: list[str] | None,
    ) -> list[SearchResult]:
        """Post-filter results to only keep memories containing ALL specified tags."""
        if not tags:
            return results
        required = set(tags)
        return [r for r in results if required.issubset(set(r.memory.tags))]

    @staticmethod
    def _filter_by_valid_at(
        results: list[SearchResult],
        valid_at: datetime,
    ) -> list[SearchResult]:
        """Post-filter results to only include memories valid at the given timestamp.

        A memory is valid at ``valid_at`` if:
        - ``valid_from`` is None OR ``valid_from <= valid_at``
        - ``valid_until`` is None OR ``valid_until > valid_at``
        """
        return [
            r
            for r in results
            if (r.memory.valid_from is None or r.memory.valid_from <= valid_at)
            and (r.memory.valid_until is None or r.memory.valid_until > valid_at)
        ]

    @staticmethod
    def _to_search_results(
        pairs: list[tuple[Memory, float]],
        source: str,
    ) -> list[SearchResult]:
        """Convert (Memory, score) tuples from strategies into SearchResult objects."""
        return [SearchResult(memory=m, score=s, source=source) for m, s in pairs]

    def _keyword_search(
        self, query: SearchQuery, date_from=None, date_to=None
    ) -> Result[list[SearchResult], SearchError]:
        """Execute keyword-only search."""
        # Empty query + tags: plain keyword/FTS return nothing, so fetch by tags directly
        if not query.text.strip() and query.tags and self._memory_repo is not None:
            return self._tag_only_search(query)
        result = self._keyword.search(
            query.text, limit=query.top_k, date_from=date_from, date_to=date_to, tags=query.tags
        )
        if not result.is_ok:
            return Failure(result.error)
        return Success(self._to_search_results(result.value, "keyword"))

    def _tag_only_search(self, query: SearchQuery) -> Result[list[SearchResult], SearchError]:
        """Fallback for tag-only retrieval (empty text + tags): fetch via get_by_tags."""
        from nous.domain.shared.errors import SearchError

        result = self._memory_repo.get_by_tags(query.tags)
        if not result.is_ok:
            return Failure(SearchError(str(result.error)))
        results = self._to_search_results([(m, 0.0) for m in result.value], "keyword")
        if query.sort == "updated_at":
            results.sort(key=lambda r: r.memory.updated_at, reverse=True)
        return Success(results[: query.top_k])

    async def _semantic_search(
        self, query: SearchQuery, date_from=None, date_to=None
    ) -> Result[list[SearchResult], SearchError]:
        """Execute semantic-only search, falling back to keyword on unavailability or error."""
        if self._semantic is None:
            return self._keyword_search(query, date_from, date_to)
        result = await self._semantic.search(query.text, limit=query.top_k, date_from=date_from, date_to=date_to)
        if not result.is_ok:
            return self._keyword_search(query, date_from, date_to)
        return Success(self._to_search_results(result.value, "semantic"))

    async def _hybrid_search(
        self, query: SearchQuery, date_from=None, date_to=None
    ) -> Result[list[SearchResult], SearchError]:
        """Execute hybrid search combining FTS5, plain keyword, and semantic results with RRF fusion."""
        # Empty query + tags: keyword/FTS return nothing, so fall back to tag-only retrieval
        if not query.text.strip() and query.tags and self._memory_repo is not None:
            return self._keyword_search(query, date_from, date_to)

        all_results: list[SearchResult] = []

        # 1. Plain LIKE keyword search (existing)
        kw_result = self._keyword.search(
            query.text, limit=query.top_k, date_from=date_from, date_to=date_to, tags=query.tags
        )
        if kw_result.is_ok:
            all_results.extend(self._to_search_results(kw_result.value, "keyword"))

        # 2. FTS5 full-text search (BM25 ranked)
        if self._memory_repo is not None and hasattr(self._memory_repo, "search_fts"):
            fts_result = self._memory_repo.search_fts(
                query.text, top_k=query.top_k * 2, date_from=date_from, date_to=date_to, tags=query.tags
            )
            if fts_result.is_ok:
                all_results.extend(self._to_search_results(fts_result.value, "fts"))

        # 3. Semantic vector search (Qdrant)
        if self._semantic is not None:
            sem_result = await self._semantic.search(
                query.text, limit=query.top_k, date_from=date_from, date_to=date_to
            )
            if sem_result.is_ok:
                sem_results = self._to_search_results(sem_result.value, "semantic")
                # Apply similarity_flag for high-confidence matches
                if query.similarity_threshold > 0:
                    for sr in sem_results:
                        if sr.score >= query.similarity_threshold:
                            sr.similarity_flag = True
                all_results.extend(sem_results)

        if not all_results:
            return Success([])

        # 4. RRF ranking with source weights
        if self._ranker is not None:
            all_results = self._ranker.rank(all_results, query)
        else:
            all_results.sort(key=lambda x: x.score, reverse=True)

        # Deduplicate by memory key, keeping highest score
        seen: dict[str, SearchResult] = {}
        for r in all_results:
            if r.memory.key not in seen or r.score > seen[r.memory.key].score:
                seen[r.memory.key] = r
        deduped = sorted(seen.values(), key=lambda x: x.score, reverse=True)

        # 5.5 Entity matching boost
        if self._entity_service is not None:
            # Extract entities from query text using the extractor
            query_entity_ids: set[str] = set()
            try:
                extracted = self._entity_service.extractor.extract(query.text)
                for name, _ in extracted:
                    eid = name.lower().strip()
                    if eid:
                        query_entity_ids.add(eid)
            except Exception:
                pass

            if query_entity_ids:
                # Find all memory keys linked to these entities
                entity_linked_keys: set[str] = set()
                for eid in query_entity_ids:
                    mem_keys_result = self._entity_service.find_related_memories(eid, limit=20)
                    if mem_keys_result.is_ok:
                        entity_linked_keys.update(mem_keys_result.value)

                # Boost results that match entity-linked memories
                if entity_linked_keys:
                    for r in deduped:
                        if r.memory.key in entity_linked_keys:
                            r.score += 0.1
                    deduped.sort(key=lambda x: x.score, reverse=True)

        # 5. Rerank step: cross-encoder refinement (if available and loaded)
        if self._reranker is not None and self._reranker.enabled:
            if self._reranker.is_loaded:
                pairs = [(r.memory.key, r.score) for r in deduped]
                contents = {r.memory.key: r.memory.content for r in deduped if r.memory.content}
                if contents:
                    try:
                        reranked = self._reranker.rerank(
                            query.text,
                            pairs,
                            contents,
                            top_k=min(len(pairs), 20),
                        )
                        score_map = dict(reranked)
                        for r in deduped:
                            new_score = score_map.get(r.memory.key)
                            if new_score is not None:
                                r.score = new_score
                        deduped.sort(key=lambda x: x.score, reverse=True)
                    except Exception:
                        logger.warning("Reranker step failed, using pre-rerank scores")
            elif not self._reranker_unloaded_warned:
                self._reranker_unloaded_warned = True
                logger.warning("Reranker not loaded; skipping rerank step")

        # 6. Spreading Activation through memory links
        if self._link_repo and deduped:
            seed_keys = [r.memory.key for r in deduped[:5]]
            all_links = self._link_repo.get_links_for_keys(seed_keys)
            if all_links:
                from nous.domain.search.spreading_activation import SpreadingActivation

                sa = SpreadingActivation(hops=2)
                activations = sa.propagate(seed_keys, all_links)
                for r in deduped:
                    if r.memory.key in activations:
                        r.score += activations[r.memory.key] * 0.2
                deduped.sort(key=lambda x: x.score, reverse=True)

        return Success(deduped[: query.top_k])

    def set_persona(self, persona: str) -> None:
        """Set the persona for semantic search."""
        if self._semantic is not None:
            self._semantic.persona = persona

    def best_search_mode(self) -> str:
        """Return the best available search mode based on current configuration."""
        cfg = self._memorag_config
        if cfg and cfg.enabled:
            return "smart"
        return "hybrid"

    async def _smart_search(self, query: SearchQuery) -> Result[list[SearchResult], SearchError]:
        """Smart search: hybrid search with simple query expansion.

        Runs the original query plus extracted sub-queries, then merges
        results using RRF to surface the most relevant memories.
        """
        all_results: list[SearchResult] = []

        # 1. Run the original hybrid search
        original = await self._hybrid_search(query)
        if original.is_ok:
            all_results.extend(original.value)

        # 2. Generate expanded sub-queries and run additional searches
        sub_queries = _expand_query(query.text)
        for sub_q in sub_queries:
            if sub_q == query.text:
                continue
            sub = SearchQuery(
                text=sub_q,
                top_k=query.top_k,
                mode="hybrid",
                tags=query.tags,
                date_range=query.date_range,
                min_importance=query.min_importance,
                importance_weight=query.importance_weight,
                recency_weight=query.recency_weight,
                vector_weight=query.vector_weight,
                keyword_weight=query.keyword_weight,
                kind=query.kind,
            )
            result = await self._hybrid_search(sub)
            if result.is_ok:
                all_results.extend(result.value)

        if not all_results:
            return Success([])

        # 3. Re-rank merged results with RRF
        if self._ranker is not None:
            all_results = self._ranker.rank(all_results, query)
        else:
            all_results.sort(key=lambda x: x.score, reverse=True)

        # Deduplicate by memory key, keeping highest score
        seen: dict[str, SearchResult] = {}
        for r in all_results:
            if r.memory.key not in seen or r.score > seen[r.memory.key].score:
                seen[r.memory.key] = r
        deduped = sorted(seen.values(), key=lambda x: x.score, reverse=True)
        return Success(deduped[: query.top_k])


def _expand_query(text: str) -> list[str]:
    """Extract sub-queries from text for smart search expansion.

    Splits on Japanese punctuation and whitespace, keeping segments longer
    than 2 characters as additional search queries alongside the original.
    """
    # Split on spaces, Japanese commas/periods, brackets, and common separators
    # \\s = regex whitespace; \uXXXX = actual Unicode chars resolved by Python
    segments = re.split("[\\s\u3000\u3001\u3002\uff0c\uff0e\u300c\u300d\u3010\u3011()\uff08\uff09\uff3b\uff3d]+", text)
    expanded = [text]  # always include original
    for seg in segments:
        seg = seg.strip()
        if len(seg) >= 2 and seg != text:
            expanded.append(seg)
    return expanded[:4]  # limit to 4 queries max
