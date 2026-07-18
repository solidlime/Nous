from __future__ import annotations

import asyncio
import contextlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime

from nous.domain.memory.contradiction import ContradictionType
from nous.domain.memory.entities import Memory, MemoryStrength
from nous.domain.memory.type_classifier import auto_tags
from nous.domain.search.engine import SearchQuery
from nous.domain.shared.errors import (
    DomainError,
    MemoryNotFoundError,
    MemoryValidationError,
)
from nous.domain.shared.result import Failure, Result, Success
from nous.domain.shared.time_utils import generate_memory_key, get_now
from nous.domain.value_objects import normalize_emotion, normalize_importance

if TYPE_CHECKING:
    from nous.domain.memory.contradiction import ContradictionDetector
    from nous.domain.memory.repository import MemoryRepository
    from nous.domain.search.engine import SearchEngine
    from nous.infrastructure.llm.memory_enricher import MemoryEnricher


class MemoryService:
    """Domain service for memory operations."""

    def __init__(
        self,
        repo: MemoryRepository,
        entity_service: object | None = None,
        enricher: MemoryEnricher | None = None,
        link_repo: object | None = None,
        search_engine: SearchEngine | None = None,
        contradiction_detector: ContradictionDetector | None = None,
    ) -> None:
        self._repo = repo
        self._entity_service = entity_service
        self._enricher = enricher
        self._link_repo = link_repo
        self._search_engine = search_engine
        self._contradiction_detector = contradiction_detector

    def save_memory(self, mem: Memory) -> Result[Memory, DomainError]:
        """Save a pre-constructed memory entity directly to the repository."""
        return self._repo.save(mem)

    def create_memory(
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
        **extra_fields: object,
    ) -> Result[Memory, DomainError]:
        """Create and persist a new memory entry.

        emotion and emotion_intensity are single-field values for the memory.
        body_state and state_snapped_at are set by the caller after capturing
        current persona state (see PersonaService.get_state_snapshot).
        body_state and state_snapped_at are set by the caller after capturing
        current persona state (see PersonaService.get_state_snapshot).

        persona is used for contradiction detection invalidation. When omitted
        the caller should ensure persona-scoped isolation at the DB layer.
        """
        if not content or not content.strip():
            return Failure(MemoryValidationError("Content must not be empty"))

        # Auto-classify content and add type tag if not already present
        type_hints = auto_tags(content.strip(), tags)
        if type_hints:
            tags = list(tags or []) + type_hints

        # Validate tags
        if tags:
            if len(tags) > 20:
                return Failure(MemoryValidationError(f"Too many tags: {len(tags)} (max 20)"))
            for tag in tags:
                if len(tag) > 50:
                    return Failure(MemoryValidationError(f"Tag too long: '{tag[:20]}...' (max 50 chars)"))

        emotion = normalize_emotion(emotion)
        now = get_now()
        key = generate_memory_key()
        memory = Memory(
            key=key,
            content=content.strip(),
            created_at=now,
            updated_at=now,
            importance=normalize_importance(importance),
            emotion=emotion,
            emotion_intensity=normalize_importance(emotion_intensity),
            tags=tags or [],
            privacy_level=privacy_level,
            source_context=source_context,
            body_state=body_state,
            state_snapped_at=state_snapped_at,
            kind=kind,
            source_type=source_type,
            confidence=confidence,
            **{k: v for k, v in extra_fields.items() if hasattr(Memory, k)},
        )
        result = self._repo.save(memory)
        if not result.is_ok:
            return Failure(result.error)

        # Record version 1
        self._repo.save_version(
            memory_key=key,
            version=1,
            content=memory.content,
            metadata=None,
            changed_by="user",
            change_type="create",
        )

        # Entity extraction hook (best-effort, never blocks create)
        if self._entity_service is not None:
            with contextlib.suppress(Exception):
                self._entity_service.extract_and_link(
                    memory_key=key,
                    content=content.strip(),
                    tags=tags,
                )

        # Memory enrichment: auto-evaluate importance + extract relations (best-effort)
        if self._enricher is not None and importance == 0.5:
            with contextlib.suppress(Exception):
                # Extract entities using Sudachi NER (accurate path) for LLM context.
                # create_memory is sync — call SudachiExtractor directly (no await needed).
                from nous.domain.memory.sudachi_extractor import (
                    HybridEntityExtractor,
                    SudachiExtractor,
                )

                hybrid = HybridEntityExtractor()
                sudachi = SudachiExtractor()
                accurate = sudachi.extract(content.strip())
                # Convert list[dict] with keys {name, type, start, end} → list[tuple[str, str]]
                extracted_entities = [(e["name"], e["type"]) for e in accurate]
                enrichment = self._enricher.enrich(
                    content=content.strip(),
                    type_tags=type_hints or [],
                    entities=extracted_entities,
                )
                if enrichment is not None:
                    # Update importance if auto-evaluated differently
                    if enrichment.importance != 0.5:
                        clamped = normalize_importance(enrichment.importance)
                        memory.importance = clamped
                        with contextlib.suppress(Exception):
                            self._repo.update(key, importance=clamped)

                    # Register auto-extracted relations
                    if enrichment.relations and self._entity_service is not None:
                        for rel in enrichment.relations:
                            with contextlib.suppress(Exception):
                                self._entity_service.add_relation(
                                    source=rel.source_entity,
                                    target=rel.target_entity,
                                    relation_type=rel.relation_type,
                                    memory_key=key,
                                    confidence=rel.confidence,
                                )

        # Hebbian co-activation links: associate with co-accessed memories
        if self._link_repo is not None:
            with contextlib.suppress(Exception):
                self._create_hebbian_links(memory)

        # Memory evolution: enrich semantically related memories (best-effort, non-blocking)
        if self._search_engine is not None:
            asyncio.create_task(
                self._evolve_related_memories(
                    content=content,
                    new_memory_key=memory.key,
                )
            )

        # Contradiction invalidation: detect similar existing memories and
        # close their validity windows (best-effort, non-blocking)
        if self._contradiction_detector is not None and self._contradiction_detector.available:
            asyncio.create_task(
                self._invalidate_contradicted_memory(
                    new_content=content.strip(),
                    new_memory_key=memory.key,
                    persona=persona or "default",
                    valid_from=now,
                )
            )

        return Success(memory)

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
           - CONTRADICTORY → tombstone existing memory.
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
            tombstoned_keys: set[str] = set()

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
                    result = self._enricher.classify_contradiction(
                        new_content=content,
                        existing_memories=candidates,
                    )
                    if result is not None and result.existing_memory_key:
                        if result.type == ContradictionType.EXTENDABLE:
                            updates = dict(result.updated_fields or {})
                            if updates:
                                self._repo.update(result.existing_memory_key, **updates)
                        elif result.type == ContradictionType.CONTRADICTORY:
                            self._repo.tombstone(result.existing_memory_key)
                            tombstoned_keys.add(result.existing_memory_key)
                        # INDEPENDENT: do nothing, both coexist

            # --- Existing evolution logic (skip tombstoned) ---
            for result in similar.value:
                existing = result.memory
                if existing.key == new_memory_key or existing.key in tombstoned_keys:
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
            pass

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
                    self._repo.update_validity_window(
                        memory_key=candidate.memory_key,
                        valid_until=valid_from,
                    )
        except Exception:
            # Invalidation is best-effort, never blocks the main flow
            pass

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

    @staticmethod
    def _classify_link_type(m1: Memory, m2: Memory) -> str:
        """Classify the associative link type between two memories."""
        if m1.emotion and m2.emotion and m1.emotion == m2.emotion:
            return "emotional"
        if m1.kind == "episodic" and m2.kind == "episodic":
            return "temporal"
        return "semantic"

    def _get_session_memories(self, _new_memory: Memory) -> list:
        """Return memories recently accessed in the current conversation turn.

        Stub implementation — always returns empty list.
        Will be wired to session_event table or in-memory turn context
        in a follow-up task.
        """
        return []

    def get_memory(self, key: str) -> Result[Memory, DomainError]:
        """Retrieve a memory by key (excludes tombstoned memories)."""
        result = self._repo.find_by_key(key)
        if not result.is_ok:
            return Failure(result.error)
        if result.value is None:
            return Failure(MemoryNotFoundError(f"Memory not found: {key}"))
        if getattr(result.value, "lifecycle_status", "active") == "tombstoned":
            return Failure(MemoryNotFoundError(f"Memory deleted: {key}"))
        return Success(result.value)

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
            if len(tag_list) > 20:
                return Failure(MemoryValidationError(f"Too many tags: {len(tag_list)} (max 20)"))
            for tag in tag_list:
                if len(str(tag)) > 50:
                    return Failure(MemoryValidationError(f"Tag too long: '{str(tag)[:20]}...' (max 50 chars)"))
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

    def get_recent(self, limit: int = 10, offset: int = 0) -> Result[list[Memory], DomainError]:
        """Get most recent memories with optional pagination offset."""
        return self._repo.find_recent(limit=limit, offset=offset)

    def count_memories(self) -> Result[int, DomainError]:
        """Count total non-tombstoned memories."""
        return self._repo.count()

    def get_stats(self, top_n: int = 20) -> Result[dict, DomainError]:
        """Get memory statistics.

        Args:
            top_n: Maximum number of entries to return in tag/emotion distributions (default 20).
        """
        count_result = self._repo.count()
        if not count_result.is_ok:
            return Failure(count_result.error)

        all_result = self._repo.find_all()
        if not all_result.is_ok:
            return Failure(all_result.error)

        memories = all_result.value
        tag_dist: dict[str, int] = {}
        emotion_dist: dict[str, int] = {}
        for m in memories:
            for tag in m.tags:
                tag_dist[tag] = tag_dist.get(tag, 0) + 1
            emotion_dist[m.emotion] = emotion_dist.get(m.emotion, 0) + 1

        total_count = count_result.value
        tagged_count = sum(1 for m in memories if m.tags)

        # Sort by count descending and truncate to top_n
        sorted_tags = sorted(tag_dist.items(), key=lambda x: -x[1])
        sorted_emotions = sorted(emotion_dist.items(), key=lambda x: -x[1])
        hidden_tags = max(0, len(sorted_tags) - top_n)
        hidden_emotions = max(0, len(sorted_emotions) - top_n)

        result: dict = {
            "total_count": total_count,
            "tag_distribution": dict(sorted_tags[:top_n]),
            "emotion_distribution": dict(sorted_emotions[:top_n]),
            "tagged_ratio": tagged_count / total_count if total_count > 0 else None,
        }
        if hidden_tags:
            result["tag_distribution_note"] = f"+ {hidden_tags} more tags (use top_n to see more)"
        if hidden_emotions:
            result["emotion_distribution_note"] = f"+ {hidden_emotions} more emotion types"
        return Success(result)

    def boost_recall(self, key: str, emotion_intensity: float | None = None) -> Result[MemoryStrength, DomainError]:
        """Boost memory strength on recall.

        Args:
            key: Memory key to boost.
            emotion_intensity: Current emotion intensity used as proxy for valence
                (Bower 1981 emotion-congruent recall). Stored in strength.valence.
        """
        strength_result = self._repo.get_strength(key)
        if not strength_result.is_ok:
            return Failure(strength_result.error)

        strength = strength_result.value
        if strength is None:
            strength = MemoryStrength(memory_key=key)

        # Store current emotion intensity as valence for emotion-congruent recall
        if emotion_intensity is not None:
            strength.valence = emotion_intensity

        strength.boost_on_recall(emotion_intensity=emotion_intensity or 0.0)
        strength.last_recall = get_now()

        save_result = self._repo.save_strength(strength)
        if not save_result.is_ok:
            return Failure(save_result.error)
        return Success(strength)

    # --- Core Memory (Memory Blocks) ---

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

    def get_memory_history(self, key: str) -> Result[list[dict], DomainError]:
        """Get version history for a memory."""
        return self._repo.get_versions(key)

    def delete_block(self, block_name: str) -> Result[None, DomainError]:
        """Delete a named memory block."""
        return self._repo.delete_block(block_name)

    def get_by_tags(self, tags: list[str], include_consumed: bool = False) -> Result[list[Memory], DomainError]:
        """Get memories that contain ALL specified tags."""
        return self._repo.get_by_tags(tags, include_consumed=include_consumed)

    # --- Smart Recent + Search Log + Gap Alert ---

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

    # --- Context Intelligence C ---

    def get_memory_index(self) -> Result[dict, DomainError]:
        """Get compressed memory index."""
        return self._repo.get_memory_index()

    def get_top_by_importance(self, limit: int = 15) -> Result[list[Memory], DomainError]:
        """Get memories ranked by importance descending."""
        return self._repo.find_top_by_importance(limit)

    def get_relationship_highlights(self, limit: int = 5) -> Result[list, DomainError]:
        """Get important relationship memories."""
        return self._repo.find_relationship_highlights(limit)
