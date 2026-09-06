"""Consolidation Worker — CraniMem-inspired two-layer (CLS) consolidation.

Replaces the old date-based extractive summarization worker.
Operates on archived memories (set by DecayWorker) and entity clusters:

1. Finds archived memories (lifecycle_status='archived', set by DecayWorker)
   that are still valid (valid_until IS NULL — F2 bitemporal contract:
   superseded memories are never gistified)
2. Groups by shared entity relations (entity_relations table)
3. Creates gist summaries from the semantic layer only; episodic memories
   stay raw (never deleted, never merged into the gist)
4. Links gist to semantic sources via related_keys + derived_from, marked
   kind='semantic' / source_type='consolidated', plus per-source
   memory_links rows (link_type='summarizes', source memory → gist node)

ADR: archived → tombstoned transition is NOT performed. Consolidated
sources stay archived (queryable history); tombstone remains reserved
for explicit user deletion (F2 contract).

Philosophy: "Memories don't disappear — they consolidate."
"""

from __future__ import annotations

import json
import threading
from typing import TYPE_CHECKING

from nous.infrastructure.logging.structured import get_logger
from nous.infrastructure.sqlite.mot_thoughts import MOT_CONFIDENCE_THRESHOLD

if TYPE_CHECKING:
    from nous.config.settings import Settings

logger = get_logger(__name__)


def _memory_entity_map(entity_repo, memory_keys: list[str]) -> dict[str, set[str]]:
    """Map memory_key → entity ids with one batch query (N+1 avoidance).

    Uses ``get_entities_for_memories`` when available; falls back to
    per-memory ``get_memory_entities`` for legacy repos.
    """
    result: dict[str, set[str]] = {k: set() for k in memory_keys}
    get_batch = getattr(entity_repo, "get_entities_for_memories", None)
    if get_batch is not None:
        try:
            for row in get_batch(list(memory_keys), limit=50) or []:
                key = row.get("memory_key")
                eid = row.get("id")
                if key in result and eid:
                    result[key].add(eid)
            return result
        except Exception:
            logger.exception("ConsolidationWorker: batch entity fetch failed; falling back")
    for key in memory_keys:
        try:
            ent_result = entity_repo.get_memory_entities(key)
        except Exception:
            logger.exception("ConsolidationWorker: entity fetch failed for %s", key)
            continue
        if ent_result.is_ok and ent_result.value:
            result[key] = {e.id for e in ent_result.value}
    return result


def _semantic_layer(memories: list) -> list:
    """Semantic layer of a group (episodic stays raw — never gistified)."""
    return [m for m in memories if getattr(m, "kind", "semantic") == "semantic"]


class ConsolidationWorker:
    """Periodically consolidates archived memories into merged summaries."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._running = False
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self.interval_seconds = 86400  # 24 hours
        self.min_memories_per_group = 3
        self.max_consolidated = 10

    def start(self) -> None:
        """Start the background consolidation thread."""
        if self._running:
            return
        self._stop_event.clear()
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True, name="consolidation-worker")
        self._thread.start()
        logger.info("ConsolidationWorker started (interval=%ds)", self.interval_seconds)

    def stop(self, timeout: float = 5.0) -> None:
        """Stop the background thread and wait for it to finish."""
        self._running = False
        self._stop_event.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=timeout)
        logger.info("ConsolidationWorker stopped")

    def _run(self) -> None:
        """Main loop: consolidate then wait (interruptible)."""
        while not self._stop_event.is_set():
            try:
                self._consolidate_all()
            except Exception:
                logger.exception("Consolidation cycle failed")
            self._stop_event.wait(self.interval_seconds)

    def _consolidate_all(self) -> None:
        """Run consolidation for all active personas."""
        from nous.application.use_cases import AppContextRegistry

        try:
            personas = list(AppContextRegistry._contexts.keys())
        except Exception:
            logger.exception("ConsolidationWorker: failed to list personas")
            return

        for persona in personas:
            try:
                ctx = AppContextRegistry.get(persona)
                self._consolidate_persona(ctx, persona)
            except Exception:
                logger.exception("ConsolidationWorker: error for persona=%s", persona)

    def _consolidate_persona(self, ctx, persona: str) -> None:
        """Consolidate archived memories for a single persona."""
        # 1. Find all non-tombstoned memories, filter for archived + still valid.
        #    Superseded (valid_until set) memories are F2 history — never gistified.
        all_result = ctx.memory_repo.find_all()
        if not all_result.is_ok or not all_result.value:
            return

        archived = [
            m for m in all_result.value if m.lifecycle_status == "archived" and getattr(m, "valid_until", None) is None
        ]
        if len(archived) < self.min_memories_per_group:
            logger.debug(
                "ConsolidationWorker: %s has %d archived (< %d)", persona, len(archived), self.min_memories_per_group
            )
            return

        logger.info("ConsolidationWorker: %s has %d archived memories", persona, len(archived))

        # 2. Build memory → entity IDs mapping (single batch query)
        mem_entities = _memory_entity_map(ctx.entity_repo, [m.key for m in archived])

        # 3. Group by shared entities
        groups = self._group_by_entities(archived, mem_entities)
        logger.info("ConsolidationWorker: %s grouped into %d entity clusters", persona, len(groups))

        # 4. Consolidate each group
        consolidated_count = 0
        # Sort groups by size descending
        sorted_groups = sorted(groups.items(), key=lambda x: -len(x[1]))
        for entity_key, memories in sorted_groups:
            if consolidated_count >= self.max_consolidated:
                break
            if len(memories) < self.min_memories_per_group:
                continue

            content = self._build_consolidated(memories)
            if content:
                self._save_consolidated(ctx, content, memories, entity_key)
                consolidated_count += 1

        logger.info(
            "ConsolidationWorker: %s complete — %d new consolidated memories",
            persona,
            consolidated_count,
        )

    def _group_by_entities(
        self,
        memories: list,
        mem_entities: dict[str, set[str]],
    ) -> dict[str, list]:
        """Group archived memories by shared entity clusters.

        Memories that share entity IDs are grouped together.
        Ungrouped memories start their own singleton group.
        """
        groups: dict[str, list] = {}
        assigned: set[str] = set()

        for mem in memories:
            if mem.key in assigned:
                continue
            # Find the best existing group or start a new one
            best_group: str | None = None
            best_overlap = 0
            for group_key, group_mems in groups.items():
                group_entities: set[str] = set()
                for gm in group_mems:
                    group_entities |= mem_entities.get(gm.key, set())
                overlap = len(mem_entities.get(mem.key, set()) & group_entities)
                if overlap > best_overlap:
                    best_overlap = overlap
                    best_group = group_key

            if best_group is not None and best_overlap > 0:
                groups[best_group].append(mem)
            else:
                groups[mem.key] = [mem]
            assigned.add(mem.key)

        return groups

    def _build_consolidated(self, memories: list) -> str | None:
        """Build a gist from the semantic layer of a group (CLS two-layer).

        Semantic memories are distilled via :meth:`_build_gist`; episodic
        memories stay raw — never merged, never deleted.
        Returns None when the group has no semantic layer (episodic-only).
        """
        if not memories:
            return None
        semantic = _semantic_layer(memories)
        if not semantic:
            return None
        return self._build_gist(semantic)

    def _build_gist(self, memories: list) -> str | None:
        """Build an extractive gist from semantic memories.

        Concatenation-based (LLM-ready for future enhancement).
        """
        if not memories:
            return None

        def _sort_key(m) -> str:
            created = m.created_at
            if isinstance(created, str):
                return created
            return created.isoformat() if created is not None else ""

        memories_sorted = sorted(memories, key=_sort_key, reverse=True)
        lines = [f"## Consolidated Gist ({len(memories)} merged)"]

        for mem in memories_sorted[:20]:  # cap at 20 per group
            created = mem.created_at
            if isinstance(created, str):
                date_str = created[:10]
            elif created is not None:
                date_str = created.date().isoformat()
            else:
                date_str = "?"
            content_preview = mem.content[:200] if mem.content else "(empty)"
            lines.append(f"- [{date_str}] {content_preview}")

        return "\n".join(lines)

    def _link_summarizes(self, ctx, gist_key: str | None, source_keys: list[str]) -> None:
        """Link each source memory → gist node in memory_links (link_type='summarizes').

        Best-effort per the wiring convention: a failed link never fails
        consolidation. ``upsert_link`` emits ``link_fire`` internally with
        its own try/except — no additional emit here.
        """
        if not gist_key:
            return
        upsert = getattr(ctx.entity_repo, "upsert_link", None)
        if upsert is None:
            return
        for key in source_keys:
            try:
                upsert(key, gist_key, link_type="summarizes")
            except Exception:
                logger.debug("summarizes link failed for %s -> %s", key, gist_key, exc_info=True)

    def _save_consolidated(
        self,
        ctx,
        content: str,
        sources: list,
        entity_key: str,
    ) -> None:
        """Save the gist memory and link it to semantic sources.

        Provenance: kind='semantic' / source_type='consolidated' /
        derived_from=[source keys as JSON]. Sources stay archived —
        no archived → tombstoned transition (ADR).
        """
        sources = _semantic_layer(sources)
        if not sources:
            return
        avg_importance = sum(m.importance for m in sources) / len(sources) if sources else 0.5
        source_keys = [m.key for m in sources]

        import asyncio as _asyncio

        result = _asyncio.run(
            ctx.memory_service.create_memory(
                content=content,
                importance=avg_importance,
                emotion="neutral",
                emotion_intensity=0.0,
                tags=["consolidated", "auto"],
                privacy_level="private",
                source_context="consolidation_worker",
                related_keys=source_keys,
                kind="semantic",
                source_type="consolidated",
                derived_from=json.dumps(source_keys, ensure_ascii=False),
            )
        )

        if result.is_ok:
            gist_key = getattr(result.value, "key", None)
            self._link_summarizes(ctx, gist_key, source_keys)
            logger.info(
                "Consolidated %d memories into key=%s (entity=%s)",
                len(sources),
                result.value,
                entity_key,
            )

        # MoT: high-confidence trace goes to a separate slot (F5).
        # Corrosion/TTL live on mot_thoughts only — never double-decayed
        # with memory_strength / memory_links.
        if result.is_ok and avg_importance >= MOT_CONFIDENCE_THRESHOLD:
            try:
                from nous.infrastructure.sqlite.mot_thoughts import save_thought  # noqa: PLC0415

                gist_key = getattr(result.value, "key", None)
                db = getattr(ctx.memory_repo, "_db", None)
                if gist_key is not None and db is not None:
                    save_thought(
                        db,
                        key=f"mot_{gist_key}",
                        consolidation_key=gist_key,
                        trace=content,
                        confidence=avg_importance,
                    )
            except Exception:
                logger.debug("MoT thought save failed", exc_info=True)
