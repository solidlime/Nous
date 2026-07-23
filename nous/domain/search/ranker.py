from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Callable

from nous.domain.search.engine import SearchQuery, SearchResult


@runtime_checkable
class ResultRanker(Protocol):
    """Protocol for result ranking strategies."""

    def rank(self, results: list[SearchResult], query: SearchQuery) -> list[SearchResult]: ...


class RRFRanker:
    """Reciprocal Rank Fusion ranker.

    ``SearchQuery.vector_weight`` applies to ``source="semantic"``.
    ``SearchQuery.keyword_weight`` applies to ``source="keyword"`` and ``source="fts"``.
    """

    def __init__(self, k: int = 60) -> None:
        self.k = k

    @staticmethod
    def _source_weight(source: str, query: SearchQuery) -> float:
        """Return RRF weight for a given source name."""
        if source == "semantic":
            return query.vector_weight if hasattr(query, "vector_weight") else 1.0
        # "keyword" or "fts" → keyword_weight
        return query.keyword_weight if hasattr(query, "keyword_weight") else 0.5

    def rank(self, results: list[SearchResult], query: SearchQuery) -> list[SearchResult]:
        """Rank results using weighted RRF formula: score = sum(weight / (k + rank_i))."""
        if not results:
            return []

        # Group by memory key, accumulating RRF scores
        scores: dict[str, float] = {}
        result_map: dict[str, SearchResult] = {}

        # Sort each source group by original score to get ranks
        by_source: dict[str, list[SearchResult]] = {}
        for r in results:
            by_source.setdefault(r.source, []).append(r)

        for source, group in by_source.items():
            weight = self._source_weight(source, query)
            group.sort(key=lambda x: x.score, reverse=True)
            for rank, r in enumerate(group):
                key = r.memory.key
                rrf_score = weight / (self.k + rank + 1)
                scores[key] = scores.get(key, 0.0) + rrf_score
                if key not in result_map or r.score > result_map[key].score:
                    result_map[key] = r

        # Apply importance and recency weight adjustments
        merged: list[SearchResult] = []
        for key, rrf_score in scores.items():
            original = result_map[key]
            adjusted_score = rrf_score

            if query.importance_weight > 0:
                adjusted_score += query.importance_weight * original.memory.importance

            if query.recency_weight > 0 and original.memory.created_at:
                from datetime import datetime

                now = datetime.now(UTC)
                created = original.memory.created_at
                if created.tzinfo is None:
                    created = created.replace(tzinfo=UTC)
                age_days = (now - created).total_seconds() / 86400
                recency_bonus = 1.0 / (1.0 + age_days)
                adjusted_score += query.recency_weight * recency_bonus

            merged.append(
                SearchResult(
                    memory=original.memory,
                    score=adjusted_score,
                    source="hybrid",
                )
            )

        merged.sort(key=lambda x: x.score, reverse=True)
        return merged


class ForgettingCurveRanker:
    """Adjusts search scores based on FSRS v6 power-law recall probability.

    ``strength_lookup`` returns ``(strength, stability)`` or ``None``.
    When stability > 0 the ranker computes the full FSRS v6 recall probability::

        R(t) = (1 + 19 * t_hours / (S * 24)) ** -0.5

    Otherwise it falls back to ``strength`` as a flat multiplier.
    """

    def __init__(
        self,
        strength_lookup: Callable[[str], tuple[float, float] | None] | None = None,
    ) -> None:
        self._lookup_fn = strength_lookup

    def rank(self, results: list[SearchResult], query: SearchQuery) -> list[SearchResult]:
        """Multiply scores by FSRS v6 recall probability."""
        if self._lookup_fn is None:
            return results

        now = datetime.now(UTC)
        adjusted: list[SearchResult] = []
        for r in results:
            strength_data = self._lookup_fn(r.memory.key)
            if strength_data is not None:
                strength_val, stability = strength_data
                if stability and stability > 0 and r.memory.created_at:
                    created = r.memory.created_at
                    if created.tzinfo is None:
                        created = created.replace(tzinfo=UTC)
                    elapsed_hours = (now - created).total_seconds() / 3600
                    recall = (1 + 19 * elapsed_hours / (stability * 24)) ** -0.5
                    new_score = r.score * (0.3 + 0.7 * recall)
                else:
                    new_score = r.score * max(0.1, strength_val)
                adjusted.append(
                    SearchResult(
                        memory=r.memory,
                        score=new_score,
                        source=r.source,
                        similarity_flag=r.similarity_flag,
                    )
                )
            else:
                # No strength data → passthrough
                adjusted.append(r)
        adjusted.sort(key=lambda x: x.score, reverse=True)
        return adjusted


class ChainedRanker:
    """Applies multiple rankers in sequence."""

    def __init__(self, *rankers: ResultRanker) -> None:
        self._rankers = rankers

    def rank(self, results: list[SearchResult], query: SearchQuery) -> list[SearchResult]:
        for ranker in self._rankers:
            results = ranker.rank(results, query)
        return results


class TopicAffinityRanker:
    """Boosts results whose memory type tag matches the inferred query topic.

    Uses ``type_classifier.classify()`` to detect the query type (decision /
    preference / milestone / problem / emotional) and adds a small bonus to
    memories already tagged with that type.  The bonus is intentionally small
    so it nudges ordering without overpowering RRF or importance signals.
    """

    def __init__(self, bonus: float = 0.025, min_confidence: float = 0.2) -> None:
        self._bonus = bonus
        self._min_confidence = min_confidence

    def rank(self, results: list[SearchResult], query: SearchQuery) -> list[SearchResult]:
        from nous.domain.memory.type_classifier import classify  # lazy import

        query_type = classify(query.text, min_confidence=self._min_confidence)
        if query_type is None:
            return results

        adjusted: list[SearchResult] = []
        for r in results:
            bonus = self._bonus if query_type in (r.memory.tags or []) else 0.0
            adjusted.append(
                SearchResult(
                    memory=r.memory,
                    score=r.score + bonus,
                    source=r.source,
                )
            )
        adjusted.sort(key=lambda x: x.score, reverse=True)
        return adjusted


class EmotionRecallBiasRanker:
    """Bower 1981: current mood boosts same-valence memories.

    Stores the current persona state (or emotion intensity proxy) and
    applies a small score boost to memories whose stored valence matches
    the current mood valence.

    The ranker is passive when no persona_state has been set — it simply
    passes results through unchanged.
    """

    def __init__(self, valence_bonus: float = 0.2) -> None:
        self._persona_state: Any = None
        self._valence_bonus = valence_bonus

    @property
    def persona_state(self) -> Any:
        return self._persona_state

    @persona_state.setter
    def persona_state(self, state: Any) -> None:
        self._persona_state = state

    def rank(self, results: list[SearchResult], query: SearchQuery) -> list[SearchResult]:
        """Boost scores for memories whose valence matches the current mood."""
        if self._persona_state is None:
            return results

        mood_valence = getattr(self._persona_state, "valence", 0.0)
        if mood_valence == 0.0:
            return results

        adjusted: list[SearchResult] = []
        for r in results:
            memory_valence = getattr(r.memory, "valence", 0.0)
            # Normalize match: 1.0 when identical, 0.0 when opposite
            valence_match = 1.0 - abs(memory_valence - mood_valence) / 2.0
            boost = 1.0 + self._valence_bonus * valence_match
            adjusted.append(
                SearchResult(
                    memory=r.memory,
                    score=r.score * boost,
                    source=r.source,
                )
            )
        adjusted.sort(key=lambda x: x.score, reverse=True)
        return adjusted
