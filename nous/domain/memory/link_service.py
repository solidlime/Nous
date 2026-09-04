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
        memory_repo: object | None = None,
        coaccess_tracker: list[str] | None = None,
    ) -> None:
        self._link_repo = link_repo
        self._search_engine_ref = search_engine_ref
        self._memory_repo = memory_repo
        # Shared mutable list owned by AppContext: keys of memories accessed
        # in the current session (rolling window, most recent last).
        self._coaccess_tracker = coaccess_tracker if coaccess_tracker is not None else []

    @property
    def _search_engine(self) -> SearchEngine | None:
        return self._search_engine_ref[0] if self._search_engine_ref else None

    def _get_session_memories(
        self,
        _new_memory: Memory,
    ) -> list[Memory]:
        """Return memories recently accessed in the current session.

        Looks up the co-access tracker keys (recorded by memory_read /
        memory_create MCP tools) via the memory repository.  Lookup
        failures (tombstoned, missing) are skipped.
        """
        if self._memory_repo is None or not self._coaccess_tracker:
            return []

        memories: list[Memory] = []
        for key in self._coaccess_tracker:
            result = self._memory_repo.find_by_key(key)  # type: ignore[attr-defined]
            if result.is_ok and result.value is not None:
                memories.append(result.value)
        return memories

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
    ) -> None:
        """Generate Hebbian links between *new_memory* and recently accessed memories.

        Hebbian co-fire principle: only memories accessed in the same session
        are linked.  Similarity-based linking (cosine >= 0.8) is deferred to
        a future async search-engine integration.
        """
        if self._link_repo is None:
            return

        co_accessed = self._get_session_memories(new_memory)
        upsert_link = getattr(self._link_repo, "upsert_link", None)
        if upsert_link is None:
            return
        # Self-link excluded first, then the 5 most RECENT accesses
        # (tracker is append-ordered: last = newest; Hebbian co-activation
        # is about temporal proximity).
        candidates = [m for m in co_accessed if m.key != new_memory.key][-5:]
        for candidate in candidates:
            link_type = self._classify_link_type(new_memory, candidate)
            upsert_link(new_memory.key, candidate.key, link_type)
