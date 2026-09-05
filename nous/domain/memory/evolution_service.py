from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime

    from nous.domain.memory.repository import MemoryRepository
    from nous.domain.search.engine import SearchEngine

from nous.domain.memory.contradiction import ContradictionType
from nous.domain.search.engine import SearchQuery
from nous.domain.shared.time_utils import get_now
from nous.domain.value_objects import normalize_importance

logger = logging.getLogger(__name__)


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
                        elif result.type == ContradictionType.CONTRADICTORY:
                            self._close_superseded_memory(result.existing_memory_key, new_memory_key)
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
        """Find existing memories that contradict the new content and close
        their validity windows (set ``valid_until = valid_from``).

        This is the core bi-temporal invalidation: old facts don't disappear,
        they just become "no longer valid" from the new fact's timestamp.
        The old memory remains queryable with ``valid_at`` filters.
        """
        if self._contradiction_detector is None:
            return
        try:
            report = await self._contradiction_detector.find_potential_contradictions(
                content=new_content,
                persona=persona,
                exclude_key=new_memory_key,
            )
            if not report.is_ok or not report.value.candidates:
                return

            threshold = report.value.threshold
            for candidate in report.value.candidates:
                if candidate.similarity >= threshold:
                    self._close_superseded_memory(candidate.memory_key, new_memory_key)
        except Exception:
            logger.debug("Contradiction invalidation failed", exc_info=True)

    async def _run_background_evolution(
        self,
        content: str,
        memory_key: str,
        persona: str,
        valid_from,
    ) -> None:
        """Run memory evolution and contradiction detection in background TaskGroup."""
        try:
            async with asyncio.TaskGroup() as tg:
                if self._search_engine is not None:
                    tg.create_task(
                        self._evolve_related_memories(
                            content=content,
                            new_memory_key=memory_key,
                        )
                    )
                if self._contradiction_detector is not None and self._contradiction_detector.available:
                    tg.create_task(
                        self._invalidate_contradicted_memory(
                            new_content=content.strip(),
                            new_memory_key=memory_key,
                            persona=persona,
                            valid_from=valid_from,
                        )
                    )
        except Exception:
            import logging

            _log = logging.getLogger(__name__)
            _log.exception("Background memory evolution/contradiction detection failed")
