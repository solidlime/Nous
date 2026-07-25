"""感情減衰計算 — recency decay for memory scoring and emotion/body decay coordination."""

from __future__ import annotations

import math
from datetime import UTC, datetime

_RECENCY_LAMBDA = 0.5  # half-life ≈ 1.4 days


def _compute_recency_decay(created_at: datetime | None) -> float:
    """Compute recency decay: exp(-λ * days_elapsed) with λ=0.5."""
    if created_at is None:
        return 0.5
    now = datetime.now(tz=UTC)
    # Ensure tz-aware comparison
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)
    days_elapsed = max(0.0, (now - created_at).total_seconds() / 86400.0)
    return math.exp(-_RECENCY_LAMBDA * days_elapsed)
