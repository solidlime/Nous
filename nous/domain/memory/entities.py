from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime

VALID_KINDS = frozenset(["episodic", "semantic", "procedural", "prospective"])
VALID_SOURCE_TYPES = frozenset(
    [
        "user_stated",
        "user_implied",
        "llm_inferred",
        "tool_output",
        # 旧 consolidation worker は 2026-11 に撤去済み。
        # 過去データの読み出し・掃除専用に値だけ残す。
        "consolidated",
        "reflected",
        "system",
    ]
)

# audit C4 — provenance modality. ``source_type`` is the single stored source of
# truth for provenance; modality is *derived* from it so the two can never drift
# apart (a second stored column would duplicate the same dimension).
VALID_MODALITIES = frozenset(["observed", "inferred", "llm_summary", "reflection"])
MODALITY_BY_SOURCE_TYPE: dict[str, str] = {
    "user_stated": "observed",
    "tool_output": "observed",
    "system": "observed",
    "user_implied": "inferred",
    "llm_inferred": "inferred",
    "consolidated": "llm_summary",
    "reflected": "reflection",
}


@dataclass
class Memory:
    """A single memory entry."""

    key: str
    content: str
    created_at: datetime
    updated_at: datetime
    importance: float = 0.5
    emotion: str = "neutral"
    emotion_intensity: float = 0.0
    tags: list[str] = field(default_factory=list)
    privacy_level: str = "internal"
    physical_state: str | None = None
    mental_state: str | None = None
    environment: str | None = None
    relationship_status: str | None = None
    source_context: str | None = None
    related_keys: list[str] = field(default_factory=list)
    summary_ref: str | None = None
    equipped_items: str | None = None
    access_count: int = 0
    last_accessed: datetime | None = None
    body_state: dict[str, float] | None = None
    state_snapped_at: datetime | None = None
    lifecycle_status: str = "active"
    last_consumed_at: datetime | None = None  # ワンショット消費用タイムスタンプ
    # kind-related fields (Chunk 1.1)
    kind: str = "semantic"  # episodic | semantic | procedural | prospective
    episodic_time: str | None = None
    episodic_place: str | None = None
    episodic_people: str | None = None  # JSON array
    # temporal validity fields (bi-temporal memory model)
    valid_from: datetime | None = None  # when this memory became valid
    valid_until: datetime | None = None  # None = currently valid
    superseded_by: str | None = None  # key of the newer memory that closed this window

    # source provenance fields (Chunk 1.4)
    source_type: str = (
        "user_stated"  # user_stated | user_implied | llm_inferred | tool_output | consolidated | reflected
    )
    confidence: float = 1.0
    derived_from: str | None = None  # JSON array of source memory keys

    def __post_init__(self) -> None:
        if self.kind not in VALID_KINDS:
            raise ValueError(f"Invalid kind: {self.kind}. Must be one of {VALID_KINDS}")
        if self.source_type not in VALID_SOURCE_TYPES:
            raise ValueError(f"Invalid source_type: {self.source_type}")

    @property
    def modality(self) -> str:
        """Provenance modality (audit C4): observed / inferred / llm_summary / reflection."""
        return MODALITY_BY_SOURCE_TYPE.get(self.source_type, "inferred")
