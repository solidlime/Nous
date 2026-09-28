"""SearchEngine: strategy orchestration, RRF fusion, and final recall scoring.

本モジュールの責務: 各 strategy（keyword / semantic / FTS）の結果を取得し、
RRF/減衰段（ranker）で融合・ランク付けする。

``SearchQuery.rank_policy`` の指定時のみ、真の recall 経路（chat pipeline の
memory retrieval）向け最終スコア段として複合スコア
（recency + importance + relevance（絶対コサイン）+ reflection penalty）を
post-filter 後に適用する。``rank_policy=None`` の経路（exploration / dup_check /
reflection / admin 検索など）は従来の RRF/減衰段で完結し、policy は一切作用しない。
"""

from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from nous.domain.memory.query_service import resolve_brain_config
from nous.domain.shared.result import Failure, Result, Success
from nous.domain.shared.time_utils import compute_recency_decay, get_now, parse_date_range
from nous.domain.value_objects import normalize_emotion

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime

    import numpy as np

    from nous.domain.memory.entities import Memory
    from nous.domain.search.policy import RankPolicy
    from nous.domain.search.ranker import ResultRanker
    from nous.domain.search.strategies import (
        KeywordSearchStrategy,
        SemanticSearchStrategy,
    )
    from nous.domain.shared.errors import SearchError
    from nous.infrastructure.sqlite.mot_thoughts import MotThought

    class ContentEncoder(Protocol):
        """ランクポリシー段が使う埋め込み器の最小契約（EmbeddingModel と構造互換）。"""

        async def async_encode_batch(self, texts: list[str], *, is_query: bool = False) -> np.ndarray: ...


from nous.infrastructure.logging.structured import get_logger

logger = get_logger(__name__)

# Query result cache: key -> (monotonic timestamp, results). TTL-only invalidation.
_CACHE_TTL_S = 30.0
_CACHE_MAX = 256
# Retrieval-induced forgetting (Anderson 1994, brain-sim design §3.4):
# suppress the top-K candidates excluded from the final recall result.
_RIF_TOP_K = 5
_STRENGTH_FLOOR = 0.005  # min_strength（nous/infrastructure/config/settings.py:91）
# FTS OR fallback（設計書 or_fallback_design.md §2d）: AND プールがこの件数未満なら
# OR で 1 回だけ追加探する。config 化は YAGNI。
FTS_OR_FALLBACK_MIN = 3


def _merge_fts_groups(
    and_results: list[tuple[Memory, float]],
    or_results: list[tuple[Memory, float]],
) -> list[tuple[Memory, float]]:
    """AND/OR の FTS 結果を key で dedup 統合し、高スコアを残す。

    これを挟まないと同キーが ranker に二度入り、RRF の rank 加算が二重計上される。
    スコア降順で返す。
    """
    merged: dict[str, tuple[Memory, float]] = {}
    for m, s in [*and_results, *or_results]:
        if m.key not in merged or s > merged[m.key][1]:
            merged[m.key] = (m, s)
    return sorted(merged.values(), key=lambda x: x[1], reverse=True)


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
    # 0.05: RRFRanker の**相対乗数**（タイブレーク方式）の重み。関連度が近い候補間で
    # のみ新しさが順位を決める（multiplier 1.0..1.05）。HTTP/MCP 両経路で同一既定。
    # MCP 側の単一定数は nous/api/mcp/_tools_memory.py:MEMORY_SEARCH_RECENCY_WEIGHT_DEFAULT。
    recency_weight: float = 0.05
    lifecycle_status: str | None = "active"
    vector_weight: float = 1.0  # RRF weight for vector/semantic signal
    # RRF weight for keyword (FTS5 + plain) signal. 0.5→1.0 に引き上げ（欠陥B）:
    # semantic が 2 倍だと正解語がコーパスに存在しても keyword 候補が上位に来ない。
    keyword_weight: float = 1.0
    similarity_threshold: float = 0.85  # cosine similarity flag threshold
    valid_at: datetime | None = None  # Only return memories valid at this timestamp
    kind: str | None = None  # episodic / semantic / procedural / prospective
    sort: str | None = None  # "updated_at" 指定時は updated_at 降順
    # Retrieval-induced forgetting gate (#081 REVIEW): only the true recall
    # path (chat pipeline memory retrieval consumed by the LLM) sets True.
    # Exploration / dup_check / reflection / admin searches stay False.
    apply_rif: bool = False
    # 真の recall 経路（chat）専用の最終スコア段。None なら従来の RRF/減衰段で完結。
    # frozen で hashable な RankPolicy をそのままキャッシュキー要素に使う。
    rank_policy: RankPolicy | None = None


@dataclass
class SearchResult:
    """A single search result with score and source info."""

    memory: Memory
    score: float
    source: str  # "semantic" | "keyword" | "fts" | "hybrid"
    similarity_flag: bool = False  # True when cosine_similarity >= threshold
    cosine: float | None = None  # rank_policy 適用時の生コサイン（clamp なし）
    graph_boost: float | None = None  # rank_policy 適用時の graph 寄与（entity + PPR/SA、debug 可視性）


class SearchEngine:
    """Orchestrates search strategies and produces ranked results."""

    def __init__(
        self,
        keyword_search: KeywordSearchStrategy,
        semantic_search: SemanticSearchStrategy | None = None,
        ranker: ResultRanker | None = None,
        memory_repo=None,
        reranker=None,
        link_repo=None,
        entity_service=None,
        embedding_provider: Callable[[], ContentEncoder | None] | None = None,
        rerank_enabled: bool = False,
    ) -> None:
        self._keyword = keyword_search
        self._semantic = semantic_search
        self._ranker = ranker
        self._memory_repo = memory_repo
        self._reranker = reranker
        self._link_repo = link_repo
        self._entity_service = entity_service
        self._embedding_provider = embedding_provider
        # 既定 False: cross-encoder rerank 段は明示的に有効化されたときのみ走る
        # （値は Settings.search.rerank_enabled / NOUS_SEARCH__RERANK_ENABLED から配線）。
        self._rerank_enabled = rerank_enabled
        self._reranker_unloaded_warned = False

    def _post_filter(self, results: list[SearchResult], query: SearchQuery) -> list[SearchResult]:
        """Apply per-request filters/sort outside the query cache.

        Bitemporal recall rule, always enforced:
        ``lifecycle != tombstoned AND (valid_until IS NULL OR valid_until > valid_at)``
        with ``valid_at`` defaulting to now.
        """
        filtered = self._filter_out_tombstoned(results)
        filtered = self._filter_by_emotion(filtered, query.emotion)
        filtered = self._filter_by_kind(filtered, query.kind)
        filtered = self._filter_by_tags(filtered, query.tags)
        effective_valid_at = query.valid_at if query.valid_at is not None else get_now()
        filtered = self._filter_by_valid_at(filtered, effective_valid_at)
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
            query.rank_policy,
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
                # cache は strategy 出力（finalize 前）を保持し、policy / post-filter
                # はリクエスト毎に適用（policy は cache key に含まれる）。
                return Success(await self._finalize(cached, query))

        if mode == "keyword":
            result = self._keyword_search(query, date_from, date_to)
        elif mode == "semantic":
            result = await self._semantic_search(query, date_from, date_to)
        elif mode == "smart":
            result = await self._smart_search(query)
        else:
            result = await self._hybrid_search(query, date_from, date_to)

        if isinstance(result, Failure):
            return result
        # Never cache empty results: cold-start fallbacks (e.g. embedding not
        # loaded yet) would otherwise poison the cache for the full TTL.
        if cache_key is not None and result.value:
            _cache_put(cache_key, result.value)
        recalled = await self._finalize(result.value, query)
        # RIF 競合選抜は現行契約どおり「engine 順の上位 top_k」を維持
        # （rank_policy 段は順位付けのみで競合 membership を変えない）。
        self._apply_rif(result.value[: query.top_k], recalled, query)
        return Success(recalled)

    async def _finalize(
        self,
        candidates: list[SearchResult],
        query: SearchQuery,
    ) -> list[SearchResult]:
        """Post-filter →（rank_policy 指定時）複合スコア段 → top_k で切る。

        「フィルタ後に切る」を唯一の切り口とする。cache hit / fresh 双方で
        同一の最終加工を保証する。
        """
        filtered = self._post_filter(candidates, query)
        if query.rank_policy is not None:
            filtered = await self._apply_rank_policy(filtered, query)
        return filtered[: query.top_k]

    async def _apply_rank_policy(
        self,
        candidates: list[SearchResult],
        query: SearchQuery,
    ) -> list[SearchResult]:
        """RankPolicy に基づく複合スコアで candidate を再順位付けする。

        composite = recency_weight * recency_decay + importance_weight * importance
                  + relevance_weight * 絶対コサイン（clamp なし）
                  + graph_boost_weight * graph_signal（entity match + PPR/SA）
        reflection タグ & penalty != 1.0 のとき composite *= penalty（全体に global 掛け）。

        relevance は semantic 検索が carry した qdrant cosine を再利用し、cosine を
        持たない候補（keyword/fts 由来）のみ再 encode する（変更B）。
        fail-open: embedding provider 無し・エンコード失敗時は relevance=0.0 で
        rec/imp のみのスコアで継続する。
        """
        policy = query.rank_policy
        assert policy is not None
        import numpy as np

        # 変更B: qdrant semantic 検索の score は cosine そのものなので
        # SearchResult.cosine に carry 済み。それを持つ候補は再 encode を省く。
        rel_by_index: dict[int, float] = {i: float(r.cosine) for i, r in enumerate(candidates) if r.cosine is not None}
        need_encode = [(i, r) for i, r in enumerate(candidates) if r.memory.content and r.cosine is None]
        encoder = self._embedding_provider() if self._embedding_provider is not None else None
        if encoder is not None and need_encode:
            try:
                qvec = (await encoder.async_encode_batch([query.text], is_query=True))[0]
            except Exception:
                logger.debug("rank_policy: query embedding failed; relevance=0.0 continues", exc_info=True)
                qvec = None
            if qvec is not None:
                try:
                    dvecs = await encoder.async_encode_batch([r.memory.content for _, r in need_encode], is_query=False)
                    for (i, _r), dvec in zip(need_encode, dvecs, strict=False):
                        try:
                            rel_by_index[i] = float(np.dot(qvec, dvec))
                        except Exception:
                            logger.debug("rank_policy: dot product failed for candidate %s", i, exc_info=True)
                            rel_by_index[i] = 0.0
                except Exception:
                    logger.debug("rank_policy: batch encode failed; relevance=0.0 continues", exc_info=True)

        # H6 案B: graph 信号（entity match + PPR/SA）を 1 回だけ計算して composite に統合。
        # graph_boost_weight=0 のときは計算自体を skip（現行 composite と完全一致）。
        graph_signal: dict[str, float] = {}
        if policy.graph_boost_weight != 0.0:
            graph_signal = self._compute_graph_signal(query, candidates)

        ranked: list[SearchResult] = []
        for i, orig in enumerate(candidates):
            rel = rel_by_index.get(i, 0.0)
            base = policy.recency_weight * compute_recency_decay(
                orig.memory.created_at
            ) + policy.importance_weight * float(getattr(orig.memory, "importance", 0.5))
            graph_boost = policy.graph_boost_weight * graph_signal.get(orig.memory.key, 0.0)
            composite = base + policy.relevance_weight * rel + graph_boost
            if policy.reflection_penalty != 1.0 and "reflection" in (orig.memory.tags or []):
                composite *= policy.reflection_penalty
            ranked.append(
                SearchResult(
                    memory=orig.memory,
                    score=composite,
                    source=orig.source,
                    similarity_flag=orig.similarity_flag,
                    cosine=rel,
                    graph_boost=graph_boost,
                )
            )
        ranked.sort(key=lambda r: r.score, reverse=True)
        return ranked

    def _apply_rif(self, candidates: list[SearchResult], recalled: list[SearchResult], query: SearchQuery) -> None:
        """Retrieval-induced forgetting: suppress top-K non-recalled competitors.

        Fires ONLY when ``query.apply_rif`` is True (true recall path).
        Competitors = the highest-ranked candidates (excluding tombstoned
        memories) that did NOT make the final recall result — at most
        ``_RIF_TOP_K`` per search, ``strength *= (1 - ρ)`` each. Recalled
        memories are untouched; importance is untouched; no wiring emit.
        Suppression failures are logged and never break the search.

        Applied on the fresh-search path only: re-applying on cache hits
        would suppress the same competitors twice within the 30s TTL.
        """
        if not query.apply_rif:
            return
        repo = self._memory_repo
        if repo is None or not candidates:
            return
        recalled_keys = {r.memory.key for r in recalled}
        competitors: list[str] = []
        for r in candidates:
            if r.memory.key in recalled_keys:
                continue
            if getattr(r.memory, "lifecycle_status", "active") == "tombstoned":
                continue
            competitors.append(r.memory.key)
            if len(competitors) >= _RIF_TOP_K:
                break
        if not competitors:
            return
        # ponytail: ρ=0.05 は文献上の根拠のない arbitrary 値（RIF 機構自体は Anderson 1994）。
        # ablation テスト（RIF ON/OFF で検索精度が変わるか）が整備されるまで演出扱い。
        rho = resolve_brain_config(repo)["brain_rif_suppression_rho"]
        if rho <= 0:
            return
        for key in competitors:
            try:
                strength_result = repo.get_strength(key)
                strength = (
                    strength_result.value if strength_result.is_ok and strength_result.value is not None else None
                )
                if strength is None:
                    continue
                strength.strength = max(_STRENGTH_FLOOR, strength.strength * (1.0 - rho))
                repo.save_strength(strength)
            except Exception:
                logger.debug("RIF suppression failed for %s", key, exc_info=True)

    @staticmethod
    def _filter_out_tombstoned(results: list[SearchResult]) -> list[SearchResult]:
        """Drop logically deleted memories (tombstone is user-delete only, never recalled)."""
        return [r for r in results if getattr(r.memory, "lifecycle_status", "active") != "tombstoned"]

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
            return []
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

        Non-datetime values (e.g. test doubles) are treated as unconstrained.
        """
        from datetime import datetime

        def _includes(r: SearchResult) -> bool:
            valid_from = r.memory.valid_from
            valid_until = r.memory.valid_until
            if valid_from is not None and not isinstance(valid_from, datetime):
                valid_from = None
            if valid_until is not None and not isinstance(valid_until, datetime):
                valid_until = None
            return (valid_from is None or valid_from <= valid_at) and (valid_until is None or valid_until > valid_at)

        return [r for r in results if _includes(r)]

    @staticmethod
    def _to_search_results(
        pairs: list[tuple[Memory, float]],
        source: str,
    ) -> list[SearchResult]:
        """Convert (Memory, score) tuples from strategies into SearchResult objects.

        ``semantic`` の score は qdrant の cosine（Distance.COSINE）なので、
        ``cosine`` に carry して rank_policy 段の再 encode を省略する。
        """
        return [
            SearchResult(memory=m, score=s, source=source, cosine=s if source == "semantic" else None) for m, s in pairs
        ]

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
        if isinstance(result, Failure):
            return Failure(result.error)
        return Success(self._to_search_results(result.value, "keyword"))

    def _tag_only_search(self, query: SearchQuery) -> Result[list[SearchResult], SearchError]:
        """Fallback for tag-only retrieval (empty text + tags): fetch via get_by_tags."""
        from nous.domain.shared.errors import SearchError

        result = self._memory_repo.get_by_tags(query.tags)
        if isinstance(result, Failure):
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
        if isinstance(result, Failure):
            return self._keyword_search(query, date_from, date_to)
        return Success(self._to_search_results(result.value, "semantic"))

    async def _hybrid_search(
        self, query: SearchQuery, date_from=None, date_to=None
    ) -> Result[list[SearchResult], SearchError]:
        """Execute hybrid search combining FTS5, plain keyword, and semantic results with RRF fusion.

        rank_policy 指定時のみ取得プールを拡大する
        （``fetch_k = min(max(top_k * 3, 15), 60)``、keyword/semantic は limit=fetch_k、
        FTS は top_k=2*fetch_k）。truncation は廃止し、deduped された全候補を返す
        （件数は ``_finalize`` の post-filter → top_k で決まる）。
        """
        # Empty query + tags: keyword/FTS return nothing, so fall back to tag-only retrieval
        if not query.text.strip() and query.tags and self._memory_repo is not None:
            return self._keyword_search(query, date_from, date_to)

        fetch_k = min(max(query.top_k * 3, 15), 60) if query.rank_policy is not None else query.top_k

        all_results: list[SearchResult] = []

        # 1. Plain LIKE keyword search (existing)
        kw_result = self._keyword.search(
            query.text, limit=fetch_k, date_from=date_from, date_to=date_to, tags=query.tags
        )
        if isinstance(kw_result, Success):
            all_results.extend(self._to_search_results(kw_result.value, "keyword"))

        # 2. FTS5 full-text search (BM25 ranked)
        fts_pairs: list[tuple[Memory, float]] = []
        if self._memory_repo is not None and hasattr(self._memory_repo, "search_fts"):
            fts_result = self._memory_repo.search_fts(
                query.text, top_k=fetch_k * 2, date_from=date_from, date_to=date_to, tags=query.tags
            )
            if isinstance(fts_result, Success):
                fts_pairs = fts_result.value

            # 2b. OR fallback — AND プールが痩せた場合のみ 1 回追加（設計 §2d）。
            # 全語一致（raw content に全語含む）文書は正規化の上限 1.0 に boost。
            raw_terms = [t for t in query.text.split() if t]
            if len(raw_terms) > 1 and len(fts_pairs) < FTS_OR_FALLBACK_MIN:
                or_result = self._memory_repo.search_fts(
                    query.text,
                    top_k=fetch_k,
                    date_from=date_from,
                    date_to=date_to,
                    tags=query.tags,
                    match_mode="or",
                )
                if isinstance(or_result, Success):
                    boosted = [(m, 1.0 if all(t in m.content for t in raw_terms) else s) for (m, s) in or_result.value]
                    fts_pairs = _merge_fts_groups(fts_pairs, boosted)

            all_results.extend(self._to_search_results(fts_pairs, "fts"))

        # 3. Semantic vector search (Qdrant)
        if self._semantic is not None:
            sem_result = await self._semantic.search(query.text, limit=fetch_k, date_from=date_from, date_to=date_to)
            if isinstance(sem_result, Success):
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

        # 5.5 Entity matching boost — H6: rank_policy 経路では score 加算しない。
        # entity 信号は _apply_rank_policy が graph_signal として composite に統合する。
        if query.rank_policy is None:
            self._apply_entity_boost(query, deduped)

        # 5. Rerank step: cross-encoder refinement (if available and loaded) —
        # H6: rank_policy 経路では skip 継続（score 置換型で composite と競合するため）。
        if query.rank_policy is None:
            self._apply_reranker(query, deduped)

        # 6. Spreading Activation through memory links — H6: rank_policy 経路では
        # score 加算しない（_apply_rank_policy が graph_signal に統合、計算は 1 回）。
        if query.rank_policy is None:
            self._apply_spreading_activation(deduped)

        # truncation しない: 件数は _finalize（post-filter → top_k）で決まる
        return Success(deduped)

    def _entity_linked_memory_keys(self, query: SearchQuery) -> set[str]:
        """query text の entity に紐づく memory key 集合（entity boost の共有部品）。

        ``_apply_entity_boost``（従来経路）と ``_compute_graph_signal``（rank_policy 経路）
        の双方から使い、挙動を一致させる。
        """
        if self._entity_service is None:
            return set()
        query_entity_ids: set[str] = set()
        try:
            extracted = self._entity_service.extractor.extract(query.text)
            for name, _ in extracted:
                eid = name.lower().strip()
                if eid:
                    query_entity_ids.add(eid)
        except Exception:
            logger.debug("entity extraction failed for query: %s", query.text, exc_info=True)
            return set()
        if not query_entity_ids:
            return set()
        entity_linked_keys: set[str] = set()
        for eid in query_entity_ids:
            mem_keys_result = self._entity_service.find_related_memories(eid, limit=20)
            if isinstance(mem_keys_result, Success):
                entity_linked_keys.update(mem_keys_result.value)
        return entity_linked_keys

    def _apply_entity_boost(self, query: SearchQuery, deduped: list[SearchResult]) -> None:
        """Boost results whose memory keys are linked to entities in the query text."""
        if self._entity_service is None:
            return
        entity_linked_keys = self._entity_linked_memory_keys(query)
        # Boost results that match entity-linked memories
        if entity_linked_keys:
            for r in deduped:
                if r.memory.key in entity_linked_keys:
                    r.score += 0.1
            deduped.sort(key=lambda x: x.score, reverse=True)

    def _spreading_activation_scores(self, seed_keys: list[str]) -> dict[str, float]:
        """seed から PPR/SA を伝播した activation 分布（spreading activation の共有部品）。"""
        if not self._link_repo or not seed_keys:
            return {}
        try:
            all_links = self._link_repo.get_links_for_keys(seed_keys)
            if all_links:
                from nous.domain.search.spreading_activation import SpreadingActivation

                # Seeds come from F2-filtered results (tombstone/validity already applied)
                sa = SpreadingActivation(hops=2, reset_prob=0.15)
                return sa.propagate(seed_keys, all_links, persona=getattr(self._semantic, "persona", None))
        except Exception:
            logger.warning("Spreading activation step failed, using pre-SA scores")
        return {}

    def _compute_graph_signal(self, query: SearchQuery, candidates: list[SearchResult]) -> dict[str, float]:
        """entity match + PPR/SA を composite 加算用の graph_signal（0..1 scale）へ集約する。

        - entity match: 1.0（現行 entity boost の +0.1 と weight=0.1 でスケール一致）
        - PPR/SA: min(act * 2.0, 1.0)（現行 ``min(act * 0.2, 0.1)`` とスケール一致）
        同一 key は合算する。entity_service / link_repo 不在・例外時は fail-open（空 dict）。
        """
        signal: dict[str, float] = {}
        for key in self._entity_linked_memory_keys(query):
            signal[key] = signal.get(key, 0.0) + 1.0
        if self._link_repo and candidates:
            seed_keys = [r.memory.key for r in candidates[:5]]
            for key, act in self._spreading_activation_scores(seed_keys).items():
                signal[key] = signal.get(key, 0.0) + min(act * 2.0, 1.0)
        return signal

    # Cross-encoder に渡す候補数の上限。deduped は最大 80 件（keyword 20 + FTS 40 +
    # semantic 20）になり得るが、CPU 環境では全件 encode に 9〜12 秒かかる。
    # 上位のみを rerank し（top_k 既定 10 より広めに 20 件）、残りは元スコアを保持する。
    #
    # ponytail: この「部分 rerank」が順位破壊の原因。cross-encoder の rerank スコアは
    # 元の RRF スコアとスケールが全く違う（rerank 後 ~0.9 vs 未 rerank の RRF ~0.03）
    # ため、rerank 済み head と未 rerank の tail を同一キーで sort すると両者が混ざる:
    # head が tail に沈む／tail が head を追い越す（実測 ja_or_005 の top1 転落、
    # all-term MRR 1.0→0.8704）。全件 rerank しない限り順位は保存されないので、本段は
    # 既定で無効。明示的に有効化されたときのみ従来動作する。
    _RERANK_CANDIDATES = 20

    def _apply_reranker(self, query: SearchQuery, deduped: list[SearchResult]) -> None:
        """Cross-encoder rerank refinement.

        既定（``rerank_enabled=False``）では no-op —— rerank を一切呼ばない。
        ``SearchEngine(rerank_enabled=True)``（配線元: ``Settings.search.rerank_enabled`` /
        ``NOUS_SEARCH__RERANK_ENABLED=true``）のときのみ、上位 ``_RERANK_CANDIDATES``
        件を rerank する（部分 rerank の順位破壊はクラス定数のコメント参照）。
        reranker 未注入 / ``reranker.enabled=False`` も no-op。
        """
        if not self._rerank_enabled:
            return
        if self._reranker is None or not self._reranker.enabled:
            return
        if self._reranker.is_loaded:
            head = deduped[: self._RERANK_CANDIDATES]
            pairs = [(r.memory.key, r.score) for r in head]
            contents = {r.memory.key: r.memory.content for r in head if r.memory.content}
            if contents:
                try:
                    reranked = self._reranker.rerank(
                        query.text,
                        pairs,
                        contents,
                        top_k=len(pairs),
                    )
                    score_map = dict(reranked)
                    for r in head:
                        new_score = score_map.get(r.memory.key)
                        if new_score is not None:
                            r.score = new_score
                    deduped.sort(key=lambda x: x.score, reverse=True)
                except Exception:
                    logger.warning("Reranker step failed, using pre-rerank scores")
        elif not self._reranker_unloaded_warned:
            self._reranker_unloaded_warned = True
            logger.warning("Reranker not loaded; skipping rerank step")

    def _apply_spreading_activation(self, deduped: list[SearchResult]) -> None:
        """Propagate activation through memory links; small capped score boost."""
        if not self._link_repo or not deduped:
            return
        seed_keys = [r.memory.key for r in deduped[:5]]
        activations = self._spreading_activation_scores(seed_keys)
        if activations:
            for r in deduped:
                if r.memory.key in activations:
                    # Cap absolute boost to prevent accumulation on hub nodes
                    r.score += min(activations[r.memory.key] * 0.2, 0.1)
            deduped.sort(key=lambda x: x.score, reverse=True)

    def set_persona(self, persona: str) -> None:
        """Set the persona for semantic search."""
        if self._semantic is not None:
            self._semantic.persona = persona

    def fetch_mot_thoughts(self, query_text: str, limit: int = 3) -> list[MotThought]:
        """Fetch MoT high-confidence thoughts in a separate slot (F5).

        Never touches fact-recall scores — callers render these as their
        own prompt block. Corrosion + TTL are applied inside.
        """
        try:
            db = getattr(self._memory_repo, "_db", None)
            if db is None:
                return []
            from nous.infrastructure.sqlite.mot_thoughts import fetch_thoughts

            return fetch_thoughts(db, query_text, limit=limit)
        except Exception:
            logger.warning("MoT thought fetch failed", exc_info=True)
            return []

    async def _smart_search(self, query: SearchQuery) -> Result[list[SearchResult], SearchError]:
        """Smart search: hybrid search with simple query expansion.

        Runs the original query plus extracted sub-queries, then merges
        results using RRF to surface the most relevant memories.
        """
        all_results: list[SearchResult] = []

        # 1. Run the original hybrid search
        original = await self._hybrid_search(query)
        if isinstance(original, Success):
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
                rank_policy=query.rank_policy,
            )
            result = await self._hybrid_search(sub)
            if isinstance(result, Success):
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
        # truncation しない: 件数は _finalize（post-filter → top_k）で決まる
        return Success(deduped)


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
