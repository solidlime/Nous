"""EmotionDecay: 時間経過による感情の自然な減衰ロジック。"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from nous.domain.persona.decay import compute_exponential_decay

if TYPE_CHECKING:
    from nous.domain.persona.entities import PersonaState
    from nous.domain.persona.service import PersonaService

logger = logging.getLogger(__name__)


@dataclass
class EmotionDecayResult:
    """Result of an emotion decay application: before→after state."""

    before_emotion: str
    before_intensity: float
    after_emotion: str
    after_intensity: float
    elapsed_hours: float


def compute_emotion_decay(intensity: float, elapsed_hours: float, half_life_hours: float = 24.0) -> float:
    """指数減衰で新しい感情強度を計算する。
    減衰係数 = 0.5^(経過時間 / effective_half_life)
    effective_half_life = base_half_life * max(0.3, intensity)  — 強度が高いほど長持ち
    """
    if elapsed_hours <= 0 or intensity <= 0.0:
        return 0.0
    effective_half_life = half_life_hours * max(0.3, intensity)
    # emotion converges to 0.0 (neutral intensity)
    return compute_exponential_decay(intensity, 0.0, effective_half_life, elapsed_hours)


async def apply_emotion_decay_if_needed(
    persona_service: PersonaService,
    persona: str,
    state: PersonaState,
    half_life_hours: float = 24.0,
) -> EmotionDecayResult | None:
    """経過時間に基づいて感情強度を減衰、永続化する。

    Returns:
        EmotionDecayResult if decay was applied, None if no change needed.
    """
    from nous.domain.shared.time_utils import get_now

    last_conv = state.last_conversation_time
    if last_conv is None:
        return None

    now = get_now()
    elapsed_hours = (now - last_conv).total_seconds() / 3600.0

    current_intensity = state.emotion_intensity or 0.0
    if current_intensity <= 0.0:
        return None

    new_intensity = compute_emotion_decay(current_intensity, elapsed_hours, half_life_hours)
    if abs(new_intensity - current_intensity) < 0.005:
        return None

    # 強度がほぼ0になったらニュートラルに戻す
    if new_intensity < 0.01:
        new_emotion = "neutral"
        new_intensity = 0.0
    else:
        new_emotion = state.emotion

    try:
        result = persona_service.update_emotion(persona, new_emotion, new_intensity, context="time_decay")
        if result.is_ok:
            decay_note = " (high intensity, slow decay)" if current_intensity >= 0.7 else ""
            logger.info(
                "EmotionDecay: %s(%.2f)→%s(%.2f) — faded over %.1fh%s",
                state.emotion,
                current_intensity,
                new_emotion,
                new_intensity,
                elapsed_hours,
                decay_note,
            )
            return EmotionDecayResult(
                before_emotion=state.emotion,
                before_intensity=current_intensity,
                after_emotion=new_emotion,
                after_intensity=new_intensity,
                elapsed_hours=elapsed_hours,
            )
        logger.warning("EmotionDecay: update_emotion failed: %s", result.error)
    except Exception as e:
        logger.warning("EmotionDecay: unexpected error: %s", e)
    return None
