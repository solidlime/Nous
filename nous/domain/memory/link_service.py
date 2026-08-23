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
        session_event_repo: object | None = None,
    ) -> None:
        self._link_repo = link_repo
        self._search_engine_ref = search_engine_ref
        self._session_event_repo = session_event_repo

    @property
    def _search_engine(self) -> SearchEngine | None:
        return self._search_engine_ref[0] if self._search_engine_ref else None

    def _get_session_memories(
        self,
        _new_memory: Memory,
        session_id: str | None = None,
    ) -> list:
        """Return memories recently accessed in the current conversation turn.

        Queries session_event table for tool.called events (memory_create,
        memory_read) in the current session, then extracts the referenced
        memory keys.

        Returns empty list when session_event_repo is unavailable or
        session_id is not set (the current state — session_id is not yet
        recorded in session_events, so plumbing is wired but inert).
        """
        if session_id is None or self._session_event_repo is None:
            return []

        try:
            events = self._session_event_repo.get_by_session(session_id, limit=20)
        except Exception:
            return []

        memory_keys: list[str] = []
        for event in events:
            if event.event_type != "tool.called":
                continue
            summary = event.summary or ""
            if "memory_create" not in summary and "memory_read" not in summary:
                continue

            # Extract memory key from result_summary patterns:
            # "memory_read: ✓ Read memory: <key>"
            if "Read memory:" in summary:
                key = summary.split("Read memory:")[-1].strip()
                if key:
                    memory_keys.append(key)

        # TODO: lookup Memory objects via repo when available
        return memory_keys

    @staticmethod
    def _classify_link_type(m1: Memory, m2: Memory) -> str:
        """Classify the associative link type between two memories."""
        if m1.emotion and m2.emotion and m1.emotion == m2.emotion:
            return "emotional"
        if m1.kind == "episodic" and m2.kind == "episodic":
            return "temporal"
        return "semantic"

    def _create_hebbian_links(
        self,
        new_memory: Memory,
        session_id: str | None = None,
    ) -> None:
        """Generate Hebbian links between *new_memory* and recently accessed memories.

        Hebbian co-fire principle: only memories accessed in the same conversation
        turn are linked.  Similarity-based linking (cosine >= 0.8) is deferred to
        a future async search-engine integration.
        """
        if self._link_repo is None:
            return

        co_accessed = self._get_session_memories(new_memory, session_id)
        for candidate in co_accessed[:5]:  # max 5 links per new memory
            if candidate.key == new_memory.key:
                continue
            link_type = self._classify_link_type(new_memory, candidate)
            self._link_repo.upsert(new_memory.key, candidate.key, link_type)
