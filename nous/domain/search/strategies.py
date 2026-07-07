from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from datetime import datetime

    from nous.domain.memory.entities import Memory
    from nous.domain.shared.errors import SearchError
    from nous.domain.shared.result import Result


@runtime_checkable
class KeywordSearchStrategy(Protocol):
    """Strategy for keyword-based memory search."""

    def search(
        self,
        query: str,
        limit: int = 10,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> Result[list[tuple[Memory, float]], SearchError]: ...


@runtime_checkable
class SemanticSearchStrategy(Protocol):
    """Strategy for semantic/vector-based memory search."""

    persona: str

    async def search(
        self,
        query: str,
        limit: int = 10,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> Result[list[tuple[Memory, float]], SearchError]: ...
