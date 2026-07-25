from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime

    from nous.domain.memory.repository import MemoryRepository
    from nous.domain.search.engine import SearchEngine

from nous.domain.memory.entities import Memory
from nous.domain.search.engine import SearchQuery
from nous.domain.shared.errors import DuplicateMemoryError, MemoryValidationError
from nous.domain.shared.time_utils import generate_memory_key, get_now
from nous.domain.value_objects import normalize_emotion, normalize_importance


class MemoryWriteService:
    """Handles duplicate detection, validation, and memory entity construction."""

    def __init__(self, repo: MemoryRepository, search_engine_ref: list) -> None:
        self._repo = repo
        self._search_engine_ref = search_engine_ref

    @property
    def _search_engine(self) -> SearchEngine | None:
        return self._search_engine_ref[0] if self._search_engine_ref else None

    def _generate_memory_key(self) -> str:
        return generate_memory_key()

    async def _check_duplicate(self, content: str) -> DuplicateMemoryError | None:
        """Check for duplicate content via semantic search + exact match.

        Returns DuplicateMemoryError with details if found, None otherwise.
        Best-effort: failures are silently swallowed (fall through to creation).
        """
        # 1. Semantic similarity check (async)
        if self._search_engine is not None:
            try:
                search_result = await self._search_engine.search(SearchQuery(text=content, top_k=3))
                if search_result.is_ok and search_result.value:
                    duplicates = [
                        {
                            "key": item.memory.key,
                            "content": item.memory.content[:100],
                            "score": item.score,
                        }
                        for item in search_result.value
                        if item.score >= 0.75
                    ]
                    if duplicates:
                        return DuplicateMemoryError(
                            "Similar memory already exists",
                            duplicate_key=None,
                            similar_to=duplicates,
                        )
            except Exception:
                pass  # Fall through to exact check

        # 2. Exact match check (sync, via repository)
        try:
            exact = self._repo.find_by_content_exact(content)
            if exact.is_ok and exact.value is not None:
                return DuplicateMemoryError(
                    f"Identical content already exists (key: {exact.value.key}). Skipped.",
                    duplicate_key=exact.value.key,
                    similar_to=None,
                )
        except Exception:
            pass  # Fall through to normal creation

        return None

    def _validate_tags(self, tags: list[str] | None) -> MemoryValidationError | None:
        """Validate tag list constraints. Returns error if invalid, None otherwise."""
        if not tags:
            return None
        if len(tags) > 20:
            return MemoryValidationError(f"Too many tags: {len(tags)} (max 20)")
        for tag in tags:
            if len(str(tag)) > 50:
                return MemoryValidationError(f"Tag too long: '{str(tag)[:20]}...' (max 50 chars)")
        return None

    def _build_memory_entity(
        self,
        content: str,
        importance: float,
        emotion: str,
        emotion_intensity: float,
        tags: list[str] | None,
        privacy_level: str,
        source_context: str | None,
        body_state: dict[str, float] | None,
        state_snapped_at: datetime | None,
        kind: str,
        source_type: str,
        confidence: float,
        **extra_fields: object,
    ) -> tuple[Memory, str, datetime]:
        """Build a Memory entity from creation parameters.

        Returns (memory, key, now) tuple.
        """
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
        return memory, key, now
