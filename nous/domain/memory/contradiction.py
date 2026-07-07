from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

from nous.domain.shared.result import Result, Success

if TYPE_CHECKING:
    from nous.domain.shared.errors import DomainError, VectorStoreError


class VectorSearchProtocol(Protocol):
    """Protocol for vector similarity search."""

    async def search(
        self, persona: str, query: str, limit: int = 10
    ) -> Result[list[tuple[str, float]], VectorStoreError]: ...


class EmbeddingProtocol(Protocol):
    """Protocol for text embedding."""

    def encode(self, text: str, *, is_query: bool = False): ...


@dataclass
class ContradictionCandidate:
    """A memory that potentially contradicts new content."""

    memory_key: str
    content: str
    similarity: float
    created_at: str


@dataclass
class ContradictionReport:
    """Report of potential contradictions found for given content."""

    query_content: str
    candidates: list[ContradictionCandidate] = field(default_factory=list)
    threshold: float = 0.85


class ContradictionDetector:
    """Vector similarity-based contradiction detection.

    Finds existing memories that are highly similar to new content,
    which may indicate contradictory or duplicate information.
    """

    def __init__(
        self,
        vector_store: VectorSearchProtocol | None = None,
        threshold: float = 0.85,
    ) -> None:
        self._vector_store = vector_store
        self._threshold = threshold

    @property
    def available(self) -> bool:
        """Whether contradiction detection is available (requires vector store)."""
        return self._vector_store is not None

    async def find_potential_contradictions(
        self,
        content: str,
        persona: str,
        exclude_key: str | None = None,
    ) -> Result[ContradictionReport, DomainError]:
        """Find existing memories that potentially contradict the given content.

        Returns memories with cosine similarity >= threshold.
        These are "similar but different" candidates that may be contradictions.
        """
        if self._vector_store is None:
            return Success(
                ContradictionReport(
                    query_content=content,
                    candidates=[],
                    threshold=self._threshold,
                )
            )

        search_result = await self._vector_store.search(persona, content, limit=10)
        if not search_result.is_ok:
            return Success(
                ContradictionReport(
                    query_content=content,
                    candidates=[],
                    threshold=self._threshold,
                )
            )

        candidates: list[ContradictionCandidate] = []
        for key, score in search_result.value:
            if exclude_key and key == exclude_key:
                continue
            if score >= self._threshold:
                candidates.append(
                    ContradictionCandidate(
                        memory_key=key,
                        content="",  # Content populated by caller if needed
                        similarity=score,
                        created_at="",
                    )
                )

        return Success(
            ContradictionReport(
                query_content=content,
                candidates=candidates,
                threshold=self._threshold,
            )
        )
