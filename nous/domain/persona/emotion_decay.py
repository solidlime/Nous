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


def compute_emotion_decay(
    emotion: str,
    intensity: float,
    elapsed_hours: float,
    half_life_hours: float | None = None,
    threshold: float | None = None,
    neutral_threshold: float | None = None,
) -> tuple[str, float]:
    """指数減衰で新しい感情強度を計算する。

    減衰係数 = 0.5^(経過時間 / effective_half_life)
    effective_half_life = base_half_life * max(0.3, intensity)

    Args:
        emotion: 現在の感情ラベル。
        intensity: 現在の強度 [0.0, 1.0]。
        elapsed_hours: 経過時間（時間）。
        half_life_hours: 半減期（デフォルト 24.0）。
        threshold: 減衰閾値（この差未満なら変化なし、デフォルト 0.005）。
        neutral_threshold: ニュートラル判定閾値（これ未満で neutral に、デフォルト 0.01）。

    Returns:
        (new_emotion, new_intensity) のタプル。
    """
    if half_life_hours is None:
        half_life_hours = 24.0
    if threshold is None:
        threshold = 0.005
    if neutral_threshold is None:
        neutral_threshold = 0.01

    if elapsed_hours <= 0 or intensity <= 0.0:
        return emotion, 0.0
    effective_half_life = half_life_hours * max(0.3, intensity)
    new_intensity = compute_exponential_decay(intensity, 0.0, effective_half_life, elapsed_hours, threshold)
    if new_intensity < neutral_threshold:
        return "neutral", 0.0
    return emotion, new_intensity


async def apply_emotion_decay_if_needed(
    persona_service: PersonaService,
    persona: str,
    state: PersonaState,
    half_life_hours: float | None = None,
    threshold: float | None = None,
    neutral_threshold: float | None = None,
) -> EmotionDecayResult | None:
    """経過時間に基づいて感情強度を減衰、永続化する。

    Args:
        persona_service: Persona service.
        persona: Persona name.
        state: 現在の PersonaState。
        half_life_hours: 半減期（デフォルト 24.0）。
        threshold: 減衰閾値（デフォルト 0.005）。
        neutral_threshold: ニュートラル判定閾値（デフォルト 0.01）。

    Returns:
        EmotionDecayResult if decay was applied, None if no change needed.
    """
    if half_life_hours is None:
        half_life_hours = 24.0
    if threshold is None:
        threshold = 0.005
    if neutral_threshold is None:
        neutral_threshold = 0.01

    from nous.domain.shared.time_utils import get_now

    last_conv = state.last_conversation_time
    if last_conv is None:
        return None

    now = get_now()
    elapsed_hours = (now - last_conv).total_seconds() / 3600.0

    current_intensity = state.emotion_intensity or 0.0
    if current_intensity <= 0.0:
        return None

    new_emotion, new_intensity = compute_emotion_decay(
        state.emotion, current_intensity, elapsed_hours,
        half_life_hours=half_life_hours,
        threshold=threshold,
        neutral_threshold=neutral_threshold,
    )
    if new_emotion == state.emotion and abs(new_intensity - current_intensity) < threshold:
        return None

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
