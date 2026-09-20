from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime

    from nous.domain.memory.repository import MemoryRepository
    from nous.domain.search.engine import SearchEngine

from nous.domain.memory.contradiction import ContradictionType
from nous.domain.memory.entities import Memory
from nous.domain.shared.time_utils import get_now
from nous.domain.value_objects import normalize_importance

logger = logging.getLogger(__name__)

# audit C4 — confidence dynamics. Confidence is *not* a ranking weight: it exists
# so that contradicted facts and re-confirmed (corroborated) facts can be told
# apart later. Nothing in the search path reads it.
CONTRADICTED_CONFIDENCE_FACTOR = 0.5
CORROBORATION_SIMILARITY_MIN = 0.9
CORROBORATION_CONFIDENCE_DELTA = 0.1

# audit M1 — interference. A new memory that is *similar* to a stored one but
# not the same fact makes that stored one harder to pull back out (retrieval
# interference, Anderson & Neely 1996). The band sits just below the
# contradiction threshold: below it the pair is unrelated, above it the fact is
# replaced rather than interfered with.
INTERFERENCE_SIM_MIN = 0.85
INTERFERENCE_SIM_MAX = 0.95
INTERFERENCE_REVIEW_THRESHOLD = 3
INTERFERENCE_REVIEW_TAG = "interference_review"


class MemoryEvolutionService:
    """Handles memory evolution, contradiction detection, and background tasks."""

    def __init__(
        self,
        search_engine_ref: list,
        repo: MemoryRepository,
        enricher: object | None,
        link_repo: object | None,
        contradiction_detector: object | None,
    ) -> None:
        self._search_engine_ref = search_engine_ref
        self._repo = repo
        self._enricher = enricher
        self._link_repo = link_repo
        self._contradiction_detector = contradiction_detector

    @property
    def _search_engine(self) -> SearchEngine | None:
        return self._search_engine_ref[0] if self._search_engine_ref else None

    async def _evolve_related_memories(
        self,
        content: str,
        new_memory_key: str,
        max_related: int = 3,
    ) -> None:
        """After creating a new memory, find semantically similar existing
        memories and enrich them by updating context and strengthening links.

        This implements the A-MEM pattern (arXiv:2502.12110) + HiMem-style
        3-op contradiction classification (ADD / UPDATE / DELETE).

        Steps:
        1. Find semantically similar existing memories.
        2. Run HiMem contradiction classification:
           - EXTENDABLE → update existing memory's metadata only.
           - CONTRADICTORY → close validity window + chain via superseded_by
             (bitemporal; old fact is kept, tombstone is user-delete only).
           - INDEPENDENT → no action (both coexist).
        3. Update access metadata, Hebbian links, and summary_ref on
           surviving memories.

        All steps are best-effort and never block the caller.
        """
        # Only run for substantive content (avoids enriching noise)
        if len(content) < 30:
            return

        try:
            from nous.domain.search.engine import SearchQuery

            # Semantically search for similar existing memories
            similar = await self._search_engine.search(
                SearchQuery(
                    text=content,
                    top_k=max_related,
                    mode="semantic",
                    similarity_threshold=0.8,
                )
            )
            if not similar.is_ok or not similar.value:
                return

            # --- HiMem-style 3-op contradiction classification ---
            invalidated_keys: set[str] = set()

            # audit M1 — interference: register near-duplicate neighbours before any
            # classification, so the counter also works with no LLM configured.
            for r in similar.value:
                if r.memory.key != new_memory_key:
                    self._register_interference(r.memory.key, new_memory_key, r.score)

            if self._enricher is not None:
                candidates = [
                    {
                        "key": r.memory.key,
                        "content": r.memory.content,
                        "similarity": r.score,
                    }
                    for r in similar.value
                    if r.memory.key != new_memory_key
                ]
                if candidates:
                    result = await self._enricher.classify_contradiction(
                        new_content=content,
                        existing_memories=candidates,
                    )
                    # Guard against LLM hallucination: only act on keys that
                    # were actually offered as candidates.
                    candidate_keys = {c["key"] for c in candidates}
                    if (
                        result is not None
                        and result.existing_memory_key
                        and result.existing_memory_key not in candidate_keys
                    ):
                        logger.warning(
                            "Contradiction LLM returned unknown key %r; skipping",
                            result.existing_memory_key,
                        )
                    elif result is not None and result.existing_memory_key:
                        matched_similarity = next(
                            (float(c["similarity"]) for c in candidates if c["key"] == result.existing_memory_key),
                            0.0,
                        )
                        if result.type == ContradictionType.EXTENDABLE:
                            updates = dict(result.updated_fields or {})
                            # Double guard: never overwrite tags/content from
                            # LLM output, even if it slips past the parser.
                            updates.pop("tags", None)
                            updates.pop("content", None)
                            if "importance" in updates:
                                updates["importance"] = normalize_importance(float(updates["importance"]))
                            if updates:
                                # 事前に既存記憶を取得し、更新前スナップショットを保存
                                existing_mem = self._repo.find_by_key(result.existing_memory_key)
                                if existing_mem.is_ok and existing_mem.value is not None:  # type: ignore[union-attr]
                                    old = existing_mem.value  # type: ignore[union-attr]
                                    snapshot = {
                                        "content": old.content,
                                        "importance": old.importance,
                                        "emotion": old.emotion,
                                        "tags": old.tags,
                                    }
                                    ver = self._repo.get_latest_version_number(result.existing_memory_key)  # type: ignore[attr-defined]
                                    next_ver = (ver.value + 1) if ver.is_ok else 1
                                    self._repo.save_version(  # type: ignore[attr-defined]
                                        memory_key=result.existing_memory_key,
                                        version=next_ver,
                                        content=old.content,
                                        metadata=snapshot,
                                        changed_by="evolution",
                                        change_type="update",
                                    )
                                self._repo.update(result.existing_memory_key, **updates)
                            # audit C4 — corroboration: the same fact is stated
                            # again at high similarity → raise confidence (cap 1.0).
                            if matched_similarity >= CORROBORATION_SIMILARITY_MIN:
                                self._adjust_confidence(
                                    result.existing_memory_key,
                                    delta=CORROBORATION_CONFIDENCE_DELTA,
                                )
                        elif result.type == ContradictionType.CONTRADICTORY:
                            self._close_superseded_memory(result.existing_memory_key, new_memory_key)
                            # audit C4 — a contradicted fact loses half its confidence.
                            self._adjust_confidence(
                                result.existing_memory_key,
                                factor=CONTRADICTED_CONFIDENCE_FACTOR,
                            )
                            invalidated_keys.add(result.existing_memory_key)
                        # INDEPENDENT: do nothing, both coexist

            # --- Existing evolution logic (skip invalidated) ---
            for result in similar.value:
                existing = result.memory
                if existing.key == new_memory_key or existing.key in invalidated_keys:
                    continue

                # 1. Update access metadata on existing memory
                existing.access_count += 1
                existing.last_accessed = get_now()
                self._repo.update(
                    existing.key,
                    access_count=existing.access_count,
                    last_accessed=existing.last_accessed,
                )

                # 2. Create or strengthen Hebbian link
                if self._link_repo is not None:
                    self._link_repo.upsert(new_memory_key, existing.key, "semantic")

                # 3. Update summary_ref on existing memory (record that
                #    newer information exists about this topic)
                if not existing.summary_ref:
                    self._repo.update(existing.key, summary_ref=new_memory_key)

        except Exception:
            # Evolution is best-effort, never blocks the main flow
            logger.debug("Memory evolution failed", exc_info=True)

    def _adjust_confidence(self, memory_key: str, factor: float = 1.0, delta: float = 0.0) -> None:
        """Best-effort confidence adjustment (audit C4): ``confidence*factor + delta``,
        clamped to [0, 1]. Never blocks the caller and never feeds ranking."""
        try:
            res = self._repo.find_by_key(memory_key)
            if not res.is_ok or res.value is None:  # type: ignore[union-attr]
                return
            current = res.value.confidence  # type: ignore[union-attr]
            new_value = min(1.0, max(0.0, current * factor + delta))
            if new_value != current:
                self._repo.update(memory_key, confidence=new_value)
        except Exception:
            logger.debug("Confidence adjustment failed for %s", memory_key, exc_info=True)

    def _register_interference(self, memory_key: str, new_memory_key: str, similarity: float) -> None:
        """audit M1 — bump the interference counter of a similar-but-not-same neighbour.

        Best-effort: a missing strength row or a save failure is not worth
        interrupting a write for.
        """
        try:
            if not (INTERFERENCE_SIM_MIN <= float(similarity) < INTERFERENCE_SIM_MAX):
                return
            res = self._repo.get_strength(memory_key)
            if not res.is_ok or res.value is None:  # type: ignore[union-attr]
                return
            strength = res.value  # type: ignore[union-attr]
            strength.interference_count += 1
            self._repo.save_strength(strength)
            if strength.interference_count >= INTERFERENCE_REVIEW_THRESHOLD:
                self._queue_interference_review(memory_key, new_memory_key, strength.interference_count)
        except Exception:
            logger.debug("Interference registration failed for %s", memory_key, exc_info=True)

    def _queue_interference_review(self, key: str, other_key: str, count: int) -> None:
        """Pair hit the merge-review threshold → queue it once (idempotent key).

        The marker is an ordinary memory tagged ``interference_review``, so it is
        findable with the existing tag search — no new table, no new index.
        """
        try:
            name = f"interference_review_{key}_{other_key}"
            existing = self._repo.find_by_key(name)
            if existing.is_ok and existing.value is not None:  # type: ignore[union-attr]
                return
            now = get_now()
            self._repo.save(
                Memory(
                    key=name,
                    content=f"Merge review candidate: {key} ↔ {other_key} (interference={count})",
                    created_at=now,
                    updated_at=now,
                    importance=0.4,
                    tags=[INTERFERENCE_REVIEW_TAG],
                    kind="semantic",
                    source_type="tool_output",
                )
            )
            logger.info("Queued interference merge review for %s ↔ %s", key, other_key)
        except Exception:
            logger.debug("Interference review queueing failed for %s", key, exc_info=True)

    def _close_superseded_memory(self, old_key: str, new_key: str) -> None:
        """Close the old memory's validity window and chain it to the new memory.

        Bitemporal invalidation: ``old.valid_until = new.valid_from`` and
        ``old.superseded_by = new.key``. The old fact is kept (no tombstone —
        tombstone is reserved for explicit user deletion).
        """
        try:
            old_res = self._repo.find_by_key(old_key)
            new_res = self._repo.find_by_key(new_key)
            if not old_res.is_ok or not new_res.is_ok:
                return
            old = old_res.value  # type: ignore[union-attr]
            new = new_res.value  # type: ignore[union-attr]
            if old is None or new is None:
                return
            if old.lifecycle_status == "tombstoned" or old.valid_until is not None:
                return  # already closed — chain stays idempotent
            valid_from = new.valid_from or get_now()
            # Snapshot pre-close state into version history (never break it)
            snapshot = {
                "content": old.content,
                "importance": old.importance,
                "emotion": old.emotion,
                "tags": old.tags,
            }
            ver = self._repo.get_latest_version_number(old_key)  # type: ignore[attr-defined]
            next_ver = (ver.value + 1) if ver.is_ok else 1
            self._repo.save_version(  # type: ignore[attr-defined]
                memory_key=old_key,
                version=next_ver,
                content=old.content,
                metadata=snapshot,
                changed_by="evolution",
                change_type="superseded",
            )
            self._repo.update_validity_window(  # type: ignore[attr-defined]
                memory_key=old_key,
                valid_until=valid_from,
                superseded_by=new_key,
            )
        except Exception:
            logger.debug("Supersede failed for %s", old_key, exc_info=True)

    async def _invalidate_contradicted_memory(
        self,
        new_content: str,
        new_memory_key: str,
        persona: str,
        valid_from: datetime,
    ) -> None:
        """Close validity windows of memories the LLM classifier marked
        CONTRADICTORY (audit H2: single classification path — the vector
        threshold path was removed; ``ContradictionDetector`` remains the
        bitemporal applier but no longer re-detects candidates itself).
        """
        # audit:H2 — 3-op LLM classification (in _evolve_related_memories) is
        # the only contradiction detector. This method is kept for external
        # callers but no longer duplicates detection; the vector-threshold
        # ContradictionDetector path was removed (supersede is applied via
        # _close_superseded_memory from the classifier result instead).
        return

    async def _run_background_evolution(
        self,
        content: str,
        memory_key: str,
        persona: str,
        valid_from,
    ) -> None:
        """Run memory evolution in background (audit H2: single task — the
        contradiction detector ran a second semantic search + LLM pass that
        duplicated the classifier's work; supersede now flows only through
        the 3-op classifier in _evolve_related_memories)."""
        try:
            if self._search_engine is not None:
                await self._evolve_related_memories(
                    content=content,
                    new_memory_key=memory_key,
                )
        except Exception:
            import logging

            _log = logging.getLogger(__name__)
            _log.exception("Background memory evolution failed")
