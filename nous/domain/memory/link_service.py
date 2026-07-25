from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nous.domain.memory.entities import Memory
    from nous.domain.search.engine import SearchEngine


class MemoryLinkService:
    """Handles Hebbian link generation between co-accessed memories."""

    def __init__(
        self,
        link_repo: object | None,
        search_engine_ref: list,
    ) -> None:
        self._link_repo = link_repo
        self._search_engine_ref = search_engine_ref

    @property
    def _search_engine(self) -> SearchEngine | None:
        return self._search_engine_ref[0] if self._search_engine_ref else None

    def _get_session_memories(self, _new_memory: Memory) -> list:
        """Return memories recently accessed in the current conversation turn.

        TODO(blocked): session_eventテーブル実装待ち

        Stub implementation — always returns empty list.
        Will be wired to session_event table or in-memory turn context
        in a follow-up task.
        """
        return []

    @staticmethod
    def _classify_link_type(m1: Memory, m2: Memory) -> str:
        """Classify the associative link type between two memories."""
        if m1.emotion and m2.emotion and m1.emotion == m2.emotion:
            return "emotional"
        if m1.kind == "episodic" and m2.kind == "episodic":
            return "temporal"
        return "semantic"

    def _create_hebbian_links(self, new_memory: Memory) -> None:
        """Generate Hebbian links between *new_memory* and recently accessed memories.

        Hebbian co-fire principle: only memories accessed in the same conversation
        turn are linked.  Similarity-based linking (cosine >= 0.8) is deferred to
        a future async search-engine integration.
        """
        if self._link_repo is None:
            return

        co_accessed = self._get_session_memories(new_memory)
        for candidate in co_accessed[:5]:  # max 5 links per new memory
            if candidate.key == new_memory.key:
                continue
            link_type = self._classify_link_type(new_memory, candidate)
            self._link_repo.upsert(new_memory.key, candidate.key, link_type)
