"""Lightweight memory context snapshot for MemoRAG-style search."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from nous.infrastructure.logging.structured import get_logger

if TYPE_CHECKING:
    from nous.infrastructure.sqlite.memory_repo import SQLiteMemoryRepository

logger = get_logger(__name__)

SNAPSHOT_BLOCK_NAME = "_global_context"
SNIPPET_MAX_CHARS = 60


@dataclass
class MemoryContextSnapshot:
    """LLM-free summary of all memories for context-aware search."""

    top_memories: list[dict] = field(default_factory=list)
    """Snippets of top-N high-importance memories."""

    top_tags: list[tuple[str, int]] = field(default_factory=list)
    """Top-10 tags by frequency."""

    emotion_dist: list[tuple[str, int]] = field(default_factory=list)
    """Emotion distribution."""

    memory_count: int = 0
    """Total memory count at snapshot build time."""

    built_at: str = ""
    """ISO timestamp of when snapshot was built."""

    @classmethod
    def build(cls, memory_repo: SQLiteMemoryRepository, top_n: int = 20) -> MemoryContextSnapshot:
        """Build snapshot from the memory repository (no LLM required)."""
        top_result = memory_repo.find_top_by_importance(limit=top_n)
        top_memories: list[dict] = []
        if top_result.is_ok:
            for mem in top_result.value:
                content = mem.content or ""
                snippet = content[:SNIPPET_MAX_CHARS] + ("…" if len(content) > SNIPPET_MAX_CHARS else "")
                top_memories.append(
                    {
                        "key": mem.key,
                        "snippet": snippet,
                        "importance": mem.importance,
                        "tags": mem.tags or [],
                        "emotion": mem.emotion or "",
                        "emotion_intensity": mem.emotion_intensity,
                        "body_state": mem.body_state,
                    }
                )

        index_result = memory_repo.get_memory_index()
        top_tags: list[tuple[str, int]] = []
        emotion_dist: list[tuple[str, int]] = []
        total_count: int = 0
        if index_result.is_ok:
            idx = index_result.value
            top_tags = idx.get("top_tags", [])[:10]
            emotion_dist = idx.get("emotion_dist", [])[:6]
            total_count = idx.get("total", 0)

        return cls(
            top_memories=top_memories,
            top_tags=top_tags,
            emotion_dist=emotion_dist,
            memory_count=total_count,
            built_at=datetime.now(UTC).isoformat(),
        )

    def to_text(self) -> str:
        """Convert snapshot to a concise text for LLM-based query expansion prompt."""
        lines: list[str] = ["=== Memory Context Snapshot ==="]
        lines.append(f"Total memories: {self.memory_count}")
        if self.top_tags:
            tags_str = ", ".join(f"{t}({n})" for t, n in self.top_tags[:8])
            lines.append(f"Top topics: {tags_str}")
        if self.emotion_dist:
            emo_str = ", ".join(f"{e}({n})" for e, n in self.emotion_dist[:5])
            lines.append(f"Emotions: {emo_str}")
        if self.top_memories:
            lines.append("High-importance memories:")
            for m in self.top_memories[:10]:
                tags = ", ".join(m["tags"][:3]) if m["tags"] else ""
                tag_suffix = f" [{tags}]" if tags else ""
                lines.append(f"  - {m['snippet']}{tag_suffix}")
        return "\n".join(lines)

    def to_json(self) -> str:
        """Serialize to JSON for storage."""
        return json.dumps(
            {
                "top_memories": self.top_memories,
                "top_tags": self.top_tags,
                "emotion_dist": self.emotion_dist,
                "memory_count": self.memory_count,
                "built_at": self.built_at,
            },
            ensure_ascii=False,
        )

    @classmethod
    def from_json(cls, data: str) -> MemoryContextSnapshot:
        """Deserialize from JSON string."""
        d = json.loads(data)
        return cls(
            top_memories=d.get("top_memories", []),
            top_tags=[tuple(x) for x in d.get("top_tags", [])],
            emotion_dist=[tuple(x) for x in d.get("emotion_dist", [])],
            memory_count=d.get("memory_count", 0),
            built_at=d.get("built_at", ""),
        )

    def is_stale(self, current_count: int, threshold: int = 20) -> bool:
        """Return True if the snapshot should be rebuilt."""
        return abs(current_count - self.memory_count) >= threshold

    def save(self, memory_repo: SQLiteMemoryRepository) -> None:
        """Persist snapshot to memory_blocks table."""
        result = memory_repo.save_block(
            block_name=SNAPSHOT_BLOCK_NAME,
            content=self.to_json(),
            block_type="global_context",
            max_tokens=2000,
            priority=100,
        )
        if not result.is_ok:
            logger.warning("Failed to save MemoryContextSnapshot: %s", result.error)

    @classmethod
    def load(cls, memory_repo: SQLiteMemoryRepository) -> MemoryContextSnapshot | None:
        """Load snapshot from memory_blocks table. Returns None if not found."""
        result = memory_repo.get_block(SNAPSHOT_BLOCK_NAME)
        if not result.is_ok or result.value is None:
            return None
        try:
            return cls.from_json(result.value["content"])
        except Exception as e:
            logger.warning("Failed to parse MemoryContextSnapshot: %s", e)
            return None
