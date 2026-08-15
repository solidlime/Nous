from __future__ import annotations

import asyncio
import contextlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime

    from nous.domain.memory.contradiction import ContradictionDetector
    from nous.domain.memory.entities import Memory, MemoryStrength
    from nous.domain.memory.repository import (
        MemoryAuxiliaryRepository,
        MemoryRepository,
        MemoryStrengthRepository,
    )
    from nous.domain.search.engine import SearchEngine
    from nous.infrastructure.llm.memory_enricher import MemoryEnricher

from nous.domain.memory.enrich_service import MemoryEnrichService
from nous.domain.memory.evolution_service import MemoryEvolutionService
from nous.domain.memory.link_service import MemoryLinkService
from nous.domain.memory.query_service import MemoryQueryService
from nous.domain.memory.type_classifier import auto_tags
from nous.domain.memory.write_service import MemoryWriteService
from nous.domain.shared.errors import (
    DomainError,
    MemoryNotFoundError,
    MemoryValidationError,
)
from nous.domain.shared.result import Failure, Result, Success
from nous.domain.shared.time_utils import get_now
from nous.domain.value_objects import normalize_emotion

# Strong references to background tasks so they aren't garbage-collected mid-flight.
_background_tasks: set[asyncio.Task] = set()


def _track_background_task(coro) -> asyncio.Task:
    """Schedule a coroutine and keep a strong reference until it completes."""
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return task


class MemoryService:
    """Domain service for memory operations — Facade over 5 sub-services."""

    def __init__(
        self,
        repo: MemoryRepository,
        entity_service: object | None = None,
        enricher: MemoryEnricher | None = None,
        link_repo: object | None = None,
        search_engine: SearchEngine | None = None,
        contradiction_detector: ContradictionDetector | None = None,
        strength_repo: MemoryStrengthRepository | None = None,
        aux_repo: MemoryAuxiliaryRepository | None = None,
        session_event_repo: object | None = None,
    ) -> None:
        self._repo = repo
        # Mutable wrapper for late search_engine injection (see use_cases.py:362)
        self._search_engine_ref: list = [search_engine]
        # Keep for inline entity extraction hook in create_memory
        self._entity_service = entity_service
        self._link_repo = link_repo
        self._contradiction_detector = contradiction_detector
        self._strength_repo = strength_repo
        self._aux_repo = aux_repo
        self._session_event_repo = session_event_repo

        # Sub-services
        self._write_service = MemoryWriteService(repo, self._search_engine_ref)
        self._enrich_service = MemoryEnrichService(enricher, entity_service, repo)
        self._link_service = MemoryLinkService(
            link_repo,
            self._search_engine_ref,
            session_event_repo=session_event_repo,
        )
        self._evolution_service = MemoryEvolutionService(
            self._search_engine_ref,
            repo,
            enricher,
            link_repo,
            contradiction_detector,
        )
        self._query_service = MemoryQueryService(repo)

    def set_search_engine(self, search_engine: SearchEngine) -> None:
        """公開API経由で検索エンジンを注入する（循環参照回避のため後付け注入）。"""
        self._search_engine_ref[0] = search_engine

    # ------------------------------------------------------------------
    # Simple repository wrappers
    # ------------------------------------------------------------------

    def save_memory(self, mem: Memory) -> Result[Memory, DomainError]:
        """Save a pre-constructed memory entity directly to the repository."""
        return self._repo.save(mem)

    # ------------------------------------------------------------------
    # create_memory — full orchestration
    # ------------------------------------------------------------------

    async def create_memory(
        self,
        content: str,
        importance: float = 0.5,
        emotion: str = "neutral",
        emotion_intensity: float = 0.0,
        tags: list[str] | None = None,
        privacy_level: str = "internal",
        source_context: str | None = None,
        persona: str | None = None,
        body_state: dict[str, float] | None = None,
        state_snapped_at: datetime | None = None,
        kind: str = "semantic",
        source_type: str = "user_stated",
        confidence: float = 1.0,
        skip_duplicate_check: bool = False,
        session_id: str | None = None,
        **extra_fields: object,
    ) -> Result[Memory, DomainError]:
        """Create and persist a new memory entry.

        emotion and emotion_intensity are single-field values for the memory.
        body_state and state_snapped_at are set by the caller after capturing
        current persona state (see PersonaService.get_state_snapshot).

        persona is used for contradiction detection invalidation. When omitted
        the caller should ensure persona-scoped isolation at the DB layer.

        skip_duplicate_check: If True, skips semantic + exact duplicate detection.

        session_id: If provided, enables session-scoped Hebbian linking via
        the session_event table.
        """
        if not content or not content.strip():
            return Failure(MemoryValidationError("Content must not be empty"))

        # ── 1. Duplicate check ──
        if not skip_duplicate_check:
            dup_error = await self._write_service._check_duplicate(content)
            if dup_error is not None:
                return Failure(dup_error)

        # ── 2. Auto-classify content type ──
        type_hints = auto_tags(content.strip(), tags)
        if type_hints:
            tags = list(tags or []) + type_hints

        # ── 3. Validate tags ──
        tag_error = self._write_service._validate_tags(tags)
        if tag_error is not None:
            return Failure(tag_error)

        # ── 4. Build memory entity ──
        memory, key, now = self._write_service._build_memory_entity(
            content=content,
            importance=importance,
            emotion=emotion,
            emotion_intensity=emotion_intensity,
            tags=tags,
            privacy_level=privacy_level,
            source_context=source_context,
            body_state=body_state,
            state_snapped_at=state_snapped_at,
            kind=kind,
            source_type=source_type,
            confidence=confidence,
            **extra_fields,
        )

        # ── 5. Persist ──
        result = self._repo.save(memory)
        if not result.is_ok:
            return Failure(result.error)

        # ── 6. Version 1 ──
        self._repo.save_version(
            memory_key=key,
            version=1,
            content=memory.content,
            metadata=None,
            changed_by="user",
            change_type="create",
        )

        # ── 7. Entity extraction hook (best-effort) ──
        if self._entity_service is not None:
            with contextlib.suppress(Exception):
                self._entity_service.extract_and_link(
                    memory_key=key,
                    content=content.strip(),
                    tags=tags,
                )

        # ── 8. Enrichment (background: LLM wait must not block create) ──
        _track_background_task(
            self._enrich_service.enrich_memory(
                memory=memory,
                content=content,
                type_hints=type_hints,
                key=key,
                importance=importance,
            )
        )

        # ── 9. Hebbian co-activation links ──
        if self._link_repo is not None:
            with contextlib.suppress(Exception):
                self._link_service._create_hebbian_links(memory, session_id)

        # ── 10. Background evolution ──
        _track_background_task(
            self._evolution_service._run_background_evolution(
                content=content,
                memory_key=memory.key,
                persona=persona or "default",
                valid_from=now,
            )
        )

        return Success(memory)

    # ------------------------------------------------------------------
    # update_memory — stays in Facade (versioning consistency)
    # ------------------------------------------------------------------

    def update_memory(self, key: str, **updates: object) -> Result[Memory, DomainError]:
        """Update fields of an existing memory."""
        existing = self._repo.find_by_key(key)
        if not existing.is_ok:
            return Failure(existing.error)
        if existing.value is None:
            return Failure(MemoryNotFoundError(f"Memory not found: {key}"))

        # Capture pre-update snapshot for versioning
        old_memory = existing.value
        snapshot = {
            "content": old_memory.content,
            "importance": old_memory.importance,
            "emotion": old_memory.emotion,
            "tags": old_memory.tags,
            "privacy_level": old_memory.privacy_level,
        }

        updates["updated_at"] = get_now()
        if "emotion" in updates:
            updates["emotion"] = normalize_emotion(str(updates["emotion"]))
        if "tags" in updates and updates["tags"]:
            tag_list = updates["tags"]
            tag_error = self._write_service._validate_tags(tag_list)
            if tag_error is not None:
                return Failure(tag_error)
        result = self._repo.update(key, **updates)
        if not result.is_ok:
            return Failure(result.error)

        # Record new version
        ver_result = self._repo.get_latest_version_number(key)
        next_ver = (ver_result.value + 1) if ver_result.is_ok else 1
        self._repo.save_version(
            memory_key=key,
            version=next_ver,
            content=str(updates.get("content", old_memory.content)),
            metadata=snapshot,
            changed_by="user",
            change_type="update",
        )

        return Success(result.value)

    # ------------------------------------------------------------------
    # delete_memory — stays in Facade (versioning consistency)
    # ------------------------------------------------------------------

    def delete_memory(self, key: str) -> Result[None, DomainError]:
        """Tombstone a memory by key (logical delete).

        Sets lifecycle_status to 'tombstoned' so search results exclude it,
        but the record remains in the database for potential recovery.
        """
        existing = self._repo.find_by_key(key)
        if not existing.is_ok:
            return Failure(existing.error)
        if existing.value is None:
            return Failure(MemoryNotFoundError(f"Memory not found: {key}"))

        # Record delete version
        old_memory = existing.value
        ver_result = self._repo.get_latest_version_number(key)
        next_ver = (ver_result.value + 1) if ver_result.is_ok else 1
        snapshot = {
            "content": old_memory.content,
            "importance": old_memory.importance,
            "emotion": old_memory.emotion,
            "tags": old_memory.tags,
        }
        self._repo.save_version(
            memory_key=key,
            version=next_ver,
            content=old_memory.content,
            metadata=snapshot,
            changed_by="user",
            change_type="delete",
        )

        return self._repo.tombstone(key)

    # ------------------------------------------------------------------
    # Query delegation
    # ------------------------------------------------------------------

    def get_memory(self, key: str) -> Result[Memory, DomainError]:
        """Retrieve a memory by key (excludes tombstoned memories)."""
        return self._query_service.get_memory(key)

    def get_recent(self, limit: int = 10, offset: int = 0) -> Result[list[Memory], DomainError]:
        """Get most recent memories with optional pagination offset."""
        return self._query_service.get_recent(limit=limit, offset=offset)

    def count_memories(self) -> Result[int, DomainError]:
        """Count total non-tombstoned memories."""
        return self._query_service.count_memories()

    def get_stats(self, top_n: int = 20) -> Result[dict, DomainError]:
        """Get memory statistics.

        Args:
            top_n: Maximum number of entries to return in tag/emotion distributions (default 20).
        """
        return self._query_service.get_stats(top_n=top_n)

    def boost_recall(self, key: str, emotion_intensity: float | None = None) -> Result[MemoryStrength, DomainError]:
        """Boost memory strength on recall.

        Args:
            key: Memory key to boost.
            emotion_intensity: Current emotion intensity used as proxy for valence
                (Bower 1981 emotion-congruent recall). Stored in strength.valence.
        """
        return self._query_service.boost_recall(key, emotion_intensity=emotion_intensity)

    def get_by_tags(self, tags: list[str], include_consumed: bool = False) -> Result[list[Memory], DomainError]:
        """Get memories that contain ALL specified tags."""
        return self._query_service.get_by_tags(tags, include_consumed=include_consumed)

    def get_memory_history(self, key: str) -> Result[list[dict], DomainError]:
        """Get version history for a memory."""
        return self._query_service.get_memory_history(key)

    def get_and_consume_one_shot(self, tag: str) -> Result[list[Memory], DomainError]:
        """Get the latest memory with the given tag and mark it as consumed.

        Used for one-shot state memories (e.g., physical_state, mental_state).
        Returns a list with the latest memory if found, else empty list.
        """
        return self._query_service.get_and_consume_one_shot(tag)

    def get_memory_index(self) -> Result[dict, DomainError]:
        """Get compressed memory index."""
        return self._query_service.get_memory_index()

    # ------------------------------------------------------------------
    # Block management
    # ------------------------------------------------------------------

    def write_block(
        self,
        block_name: str,
        content: str,
        **opts: object,
    ) -> Result[None, DomainError]:
        """Write a named memory block."""
        if not block_name or not block_name.strip():
            return Failure(MemoryValidationError("Block name must not be empty"))
        if not content:
            return Failure(MemoryValidationError("Block content must not be empty"))
        return self._repo.save_block(
            block_name=block_name.strip(),
            content=content,
            block_type=str(opts.get("block_type", "custom")),
            max_tokens=int(opts.get("max_tokens", 500)),
            priority=int(opts.get("priority", 0)),
            metadata=opts.get("metadata") if isinstance(opts.get("metadata"), dict) else None,
        )

    def read_block(self, block_name: str) -> Result[dict | None, DomainError]:
        """Read a named memory block."""
        return self._repo.get_block(block_name)

    def list_blocks(self) -> Result[list[dict], DomainError]:
        """List all memory blocks."""
        return self._repo.list_blocks()

    def delete_block(self, block_name: str) -> Result[None, DomainError]:
        """Delete a named memory block."""
        return self._repo.delete_block(block_name)

    # ------------------------------------------------------------------
    # Smart Recent + Search Log + Gap Alert
    # ------------------------------------------------------------------

    def get_smart_recent(self, limit: int = 8) -> Result[list[Memory], DomainError]:
        """Get memories ranked by smart score (importance * recency * strength)."""
        return self._repo.find_smart_recent(limit)

    def log_search(self, query: str, mode: str, result_count: int) -> Result[None, DomainError]:
        """Log a search query."""
        return self._repo.log_search(query, mode, result_count)

    def get_recent_searches(self, limit: int = 5) -> Result[list[dict], DomainError]:
        """Get recent search queries for topic detection."""
        return self._repo.get_recent_searches(limit)

    def count_decayed_important(self) -> Result[int, DomainError]:
        """Count important memories with low strength."""
        return self._repo.count_decayed_important()

    # ------------------------------------------------------------------
    # Context Intelligence C
    # ------------------------------------------------------------------

    def get_top_by_importance(self, limit: int = 15) -> Result[list[Memory], DomainError]:
        """Get memories ranked by importance descending."""
        return self._repo.find_top_by_importance(limit)

    def get_relationship_highlights(self, limit: int = 5) -> Result[list, DomainError]:
        """Get important relationship memories."""
        return self._repo.find_relationship_highlights(limit)
