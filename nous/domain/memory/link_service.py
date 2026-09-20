from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nous.domain.memory.entities import Memory
    from nous.domain.search.engine import SearchEngine


class MemoryLinkService:
    """Handles Hebbian link generation between co-accessed memories."""

    # audit M4 — temporal links: two episodes from the same day *and* the same
    # place start out stronger (event-cluster encoding: what happened together
    # is recalled together). Bonus only raises the initial weight; afterwards
    # the usual Oja-normalised Hebbian update takes over.
    TEMPORAL_BONUS_SAME_DAY = 0.15
    TEMPORAL_BONUS_SAME_PLACE = 0.15

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

    @staticmethod
    def _day_key(memory: Memory) -> str:
        """Date an episode belongs to: `episodic_time` if set, else `created_at`."""
        episodic_time = getattr(memory, "episodic_time", None)
        if isinstance(episodic_time, str) and len(episodic_time) >= 10:
            return episodic_time[:10]
        created = getattr(memory, "created_at", None)
        return created.strftime("%Y-%m-%d") if hasattr(created, "strftime") else ""

    @classmethod
    def _temporal_bonus(cls, m1: Memory, m2: Memory) -> float:
        """Initial weight bonus for two episodes (audit M4). 0.0 for anything else."""
        if getattr(m1, "kind", None) != "episodic" or getattr(m2, "kind", None) != "episodic":
            return 0.0
        bonus = 0.0
        day1, day2 = cls._day_key(m1), cls._day_key(m2)
        if day1 and day1 == day2:
            bonus += cls.TEMPORAL_BONUS_SAME_DAY
        place1 = getattr(m1, "episodic_place", None)
        if place1 and place1 == getattr(m2, "episodic_place", None):
            bonus += cls.TEMPORAL_BONUS_SAME_PLACE
        return bonus

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
            strength = 0.1 + self._temporal_bonus(new_memory, candidate)
            upsert_link(new_memory.key, candidate.key, link_type, strength=strength)
