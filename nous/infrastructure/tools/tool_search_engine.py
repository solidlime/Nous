from __future__ import annotations

from dataclasses import dataclass

from nous.domain.search.ranker import RRFRanker
from nous.infrastructure.logging.structured import get_logger
from nous.infrastructure.tools.tool_vector_store import ToolVectorStore

logger = get_logger(__name__)


@dataclass
class ToolSearchResult:
    """Represents a tool search result."""
    tool_name: str
    description: str
    input_schema: dict
    score: float


class ToolSearchEngine:
    """Hybrid tool search combining semantic + keyword matching."""

    def __init__(self, vector_store: ToolVectorStore) -> None:
        self._vector_store = vector_store
        self._ranker = RRFRanker(k=60)

    async def search(self, query: str, top_k: int = 5) -> list[ToolSearchResult]:
        """Search for matching tools. Combines Qdrant semantic search with keyword scoring.

        Args:
            query: Natural language query from LLM
            top_k: Max results to return

        Returns:
            Ranked list of ToolSearchResult
        """
        if not query.strip():
            return []

        # Qdrant semantic search (fetch 3x for better recall)
        semantic_results = await self._vector_store.search(query, limit=top_k * 3)

        # Convert to score dict for RRF ranking
        # Each result is (payload_dict, cosine_score)
        # We assign semantic scores and run keyword bonus
        combined: list[tuple[dict, float, str]] = []
        for payload, score in semantic_results:
            name = payload.get("tool_name", "")
            desc = payload.get("description", "")
            # Keyword bonus: exact name match
            keyword_score = self._keyword_score(query, name, desc)
            # Combine: 0.7 semantic + 0.3 keyword
            final_score = score * 0.7 + keyword_score * 0.3
            combined.append((payload, final_score, "hybrid"))

        # Sort by score descending
        combined.sort(key=lambda x: x[1], reverse=True)

        results = []
        seen = set()
        for payload, score, _ in combined[:top_k]:
            name = payload["tool_name"]
            if name in seen:
                continue
            seen.add(name)
            results.append(
                ToolSearchResult(
                    tool_name=name,
                    description=payload.get("description", ""),
                    input_schema=payload.get("input_schema", {}),
                    score=round(score, 4),
                )
            )

        logger.info(
            "ToolSearchEngine: query=%r → %d results (from %d candidates)",
            query[:80], len(results), len(combined),
        )
        return results

    @staticmethod
    def _keyword_score(query: str, name: str, description: str) -> float:
        """Keyword matching score. Simple token overlap with name-weighted bonus."""
        query_lower = query.lower()
        name_lower = name.lower()
        desc_lower = description.lower()

        # Exact name match → top score
        if query_lower == name_lower:
            return 1.0
        if query_lower in name_lower:
            return 0.8

        # Token overlap
        query_tokens = set(query_lower.split())
        name_tokens = set(name_lower.replace("_", " ").split())
        desc_tokens = set(desc_lower.split())

        name_overlap = len(query_tokens & name_tokens) / max(len(query_tokens), 1)
        desc_overlap = len(query_tokens & desc_tokens) / max(len(query_tokens), 1)

        return name_overlap * 0.6 + desc_overlap * 0.2
