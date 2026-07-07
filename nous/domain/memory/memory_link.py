"""Memory link domain object — Collins & Loftus 1975 spreading activation network.

A ``MemoryLink`` represents an associative connection between two memory entries.
Weight strengthens via Hebbian co-activation (co-fire → strengthen).
Unused links decay over time (spontaneous decay).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

LINK_TYPES = frozenset(["semantic", "temporal", "emotional", "contextual", "causal"])


@dataclass
class MemoryLink:
    """Associative link between two memory entries.

    Attributes:
        source_key: Key of the source memory.
        target_key: Key of the target memory.
        weight: Link strength 0.1–1.0 (default 0.5).
        link_type: Categorisation of the link (semantic, temporal, …).
        co_activation_count: How many times the pair has been co-accessed.
        last_activated: ISO‑8601 timestamp of the most recent co‑activation.
    """

    source_key: str
    target_key: str
    weight: float = 0.5
    link_type: str = "semantic"
    co_activation_count: int = 0
    last_activated: str | None = None

    def __post_init__(self) -> None:
        if self.link_type not in LINK_TYPES:
            raise ValueError(f"Invalid link_type: {self.link_type!r}. Must be one of {sorted(LINK_TYPES)}")

    def hebbian_update(self, strength: float = 0.1) -> None:
        """Hebbian co-fire principle: co-activation strengthens the link.

        Weight is capped at 1.0.  Co-activation count is incremented and
        ``last_activated`` is refreshed to the current UTC time.
        """
        self.weight = min(1.0, self.weight + strength)
        self.co_activation_count += 1
        self.last_activated = datetime.now(UTC).isoformat()

    def decay(self, rate: float = 0.01) -> None:
        """Spontaneous decay for unused links.  Weight floor at 0.1."""
        self.weight = max(0.1, self.weight - rate)
