from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime

VALID_KINDS = frozenset(["episodic", "semantic", "procedural", "prospective"])
VALID_SOURCE_TYPES = frozenset(
    ["user_stated", "user_implied", "llm_inferred", "tool_output", "consolidated", "reflected"]
)


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
    # kind-related fields (Chunk 1.1)
    kind: str = "semantic"  # episodic | semantic | procedural | prospective
    episodic_time: str | None = None
    episodic_place: str | None = None
    episodic_people: str | None = None  # JSON array
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


@dataclass
class MemoryStrength:
    """FSRS v6 power-law forgetting curve + 7-factor scoring for a memory."""

    memory_key: str
    strength: float = 1.0
    stability: float = 1.0
    last_decay: datetime | None = None
    recall_count: int = 0
    last_recall: datetime | None = None
    last_utility: datetime | None = None
    interference_count: int = 0
    link_count: int = 0
    emotion_peak: float = 0.0
    is_ltm: bool = False
    valence: float = 0.0  # -1.0 (negative) ~ +1.0 (positive)

    def compute_recall(self, elapsed_hours: float, decay_exponent: float = 0.5) -> float:
        """R(t) = (1 + 19 * t_hours / (S * 24))^(-decay_exponent).

        Canonical FSRS v6 power-law decay. S = stability in days.
        At t = S*24h (one stability period), R = 20^(-0.5) ≈ 0.224.

        Args:
            elapsed_hours: Time since last decay in hours.
            decay_exponent: FSRS decay exponent (default 0.5 = canonical).
        """
        if self.stability <= 0:
            return 0.0
        return (1 + 19.0 * elapsed_hours / (self.stability * 24)) ** (-decay_exponent)

    def compute_strength_score(
        self,
        importance: float = 0.5,
        now: datetime | None = None,
    ) -> float:
        """9-factor composite strength score (0.0-1.0).

        Factors:
        - recency: 0.20 * exp(-age_days / 7)
        - frequency: 0.15 * min(1.0, log(1+recall_count)/log(10))
        - importance: 0.25 * importance
        - utility: 0.20 * exp(-utility_age_days / 3) if last_utility else 0.0
        - novelty: 0.05 * 0.5  (stub)
        - confidence: 0.10 * 0.8  (stub)
        - interference: -0.05 * min(1.0, interference_count / 5)  (penalty)
        - chain: +0.02 * link_count (max +0.10, linked memories decay slower)
        - emotion: +0.20 * emotion_peak (max +0.10, emotional salience)
        """
        if now is None:
            now = datetime.now()

        # Recency: 7-day half-life
        age_days = (now - self.last_recall).total_seconds() / 86400 if self.last_recall is not None else 365.0
        recency = 0.20 * math.exp(-age_days / 7.0)

        # Frequency: log-scaled recall count
        frequency = 0.15 * min(1.0, math.log(1 + self.recall_count) / math.log(10))

        # Importance: direct factor
        importance_score = 0.25 * max(0.0, min(1.0, importance))

        # Utility: 3-day half-life
        if self.last_utility is not None:
            utility_age = (now - self.last_utility).total_seconds() / 86400
            utility = 0.20 * math.exp(-utility_age / 3.0)
        else:
            utility = 0.0

        # Novelty: stub (0.5 = average novelty)
        novelty = 0.05 * 0.5

        # Confidence: stub (0.8 = default confidence)
        confidence = 0.10 * 0.8

        # Interference: penalty
        interference = -0.05 * min(1.0, self.interference_count / 5.0)

        # Chain-aware boost: linked memories decay slower
        chain = 0.0
        if self.link_count > 0:
            chain = min(0.10, 0.02 * self.link_count)  # max +0.10 (5+ links)

        # Emotion boost: emotional memories are stronger
        emotion = 0.0
        if self.emotion_peak > 0.0:
            emotion = min(0.10, 0.20 * self.emotion_peak)  # max +0.10 (intensity >= 0.5)

        score = recency + frequency + importance_score + utility + novelty + confidence + interference + chain + emotion
        return max(0.0, min(1.0, score))

    def boost_on_recall(self, emotion_intensity: float = 0.0) -> None:
        """Increase stability on successful recall + update emotion peak."""
        self.recall_count += 1
        self.stability = min(self.stability * 1.5, 365.0)
        self.strength = 1.0
        self.last_recall = datetime.now()
        self.emotion_peak = max(self.emotion_peak, emotion_intensity)
