"""RelationshipDecay: 時間経過による関係性の自然な減衰ロジック。"""

from __future__ import annotations

import logging

from nous.domain.persona.decay import compute_exponential_decay

logger = logging.getLogger(__name__)


def compute_relationship_decay(current_intensity: float, elapsed_hours: float, half_life_hours: float = 168.0) -> float:
    """関係性強度の時間減衰を計算。

    放置時間が長いほど関係性が冷める（0.0に収束）。
    half_life はデフォルト7日（168時間）。親密な関係ほど長く設定可。
    """
    if elapsed_hours <= 0 or current_intensity <= 0.0:
        return current_intensity
    return compute_exponential_decay(current_intensity, 0.0, half_life_hours, elapsed_hours, threshold=0.01)
