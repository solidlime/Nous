"""Consolidation Worker — CraniMem-inspired memory consolidation.

Replaces the old date-based extractive summarization worker.
Operates on archived memories (set by DecayWorker) and entity clusters:

1. Finds archived memories (lifecycle_status='archived', set by DecayWorker)
2. Groups by shared entity relations (entity_relations table)
3. Creates consolidated summary memories
4. Links consolidated memory to sources via related_keys

Philosophy: "Memories don't disappear — they consolidate."
"""

from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING

from nous.infrastructure.logging.structured import get_logger

if TYPE_CHECKING:
    from nous.config.settings import Settings

logger = get_logger(__name__)


class ConsolidationWorker:
    """Periodically consolidates archived memories into merged summaries."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._running = False
        self._thread: threading.Thread | None = None
        self.interval_seconds = 86400  # 24 hours
        self.min_memories_per_group = 3
        self.max_consolidated = 10

    def start(self) -> None:
        """Start the background consolidation thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True, name="consolidation-worker")
        self._thread.start()
        logger.info("ConsolidationWorker started (interval=%ds)", self.interval_seconds)

    def stop(self) -> None:
        """Stop the background thread."""
        self._running = False
        logger.info("ConsolidationWorker stopping")

    def _run(self) -> None:
        """Main loop: sleep then consolidate."""
        while self._running:
            try:
                self._consolidate_all()
            except Exception:
                logger.exception("Consolidation cycle failed")
            time.sleep(self.interval_seconds)

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
        # 1. Find all non-tombstoned memories, filter for archived
        all_result = ctx.memory_repo.find_all()
        if not all_result.is_ok or not all_result.value:
            return

        archived = [m for m in all_result.value if m.lifecycle_status == "archived"]
        if len(archived) < self.min_memories_per_group:
            logger.debug(
                "ConsolidationWorker: %s has %d archived (< %d)", persona, len(archived), self.min_memories_per_group
            )
            return

        logger.info("ConsolidationWorker: %s has %d archived memories", persona, len(archived))

        # 2. Build memory → entity IDs mapping
        mem_entities: dict[str, set[str]] = {}
        for mem in archived:
            ent_result = ctx.entity_repo.get_memory_entities(mem.key)
            if ent_result.is_ok and ent_result.value:
                mem_entities[mem.key] = {e.id for e in ent_result.value}
            else:
                mem_entities[mem.key] = set()

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
        """Build a consolidated summary from a group of archived memories.

        Concatenation-based (LLM-ready for future enhancement).
        """
        if not memories:
            return None

        memories_sorted = sorted(memories, key=lambda m: m.created_at or "", reverse=True)
        lines = [f"## Consolidated Memory Group ({len(memories)} merged)"]

        for mem in memories_sorted[:20]:  # cap at 20 per group
            date_str = mem.created_at[:10] if mem.created_at else "?"
            content_preview = mem.content[:200] if mem.content else "(empty)"
            lines.append(f"- [{date_str}] {content_preview}")

        return "\n".join(lines)

    def _save_consolidated(
        self,
        ctx,
        content: str,
        sources: list,
        entity_key: str,
    ) -> None:
        """Save the consolidated memory and link it to sources."""
        avg_importance = sum(m.importance for m in sources) / len(sources) if sources else 0.5

        import asyncio as _asyncio

        result = _asyncio.run(ctx.memory_service.create_memory(
            content=content,
            importance=avg_importance,
            emotion="neutral",
            emotion_intensity=0.0,
            tags=["consolidated", "auto"],
            privacy_level="private",
            source_context="consolidation_worker",
            related_keys=[m.key for m in sources],
        ))

        if result.is_ok:
            logger.info(
                "Consolidated %d memories into key=%s (entity=%s)",
                len(sources),
                result.value,
                entity_key,
            )
