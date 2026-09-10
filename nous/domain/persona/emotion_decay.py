"""EmotionDecay: 時間経過による感情の自然な減衰ロジック。"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from nous.domain.persona.decay import compute_exponential_decay
from nous.domain.shared.result import Failure

if TYPE_CHECKING:
    from nous.domain.persona.entities import PersonaState
    from nous.domain.persona.service import PersonaService

logger = logging.getLogger(__name__)

# ── 感情カテゴリ別半減期（校正版 2026-09-10 / Verduyn & Lavrijsen 2015, Verduyn 2011 準拠）──
# 軸: 「エピソード持続時間」(valence は value_objects._EMOTION_VA_MAP 表示用に残し減衰に使わない)。
# 文献は相対順位のみ提供。絶対値 24h ベースは設計値（文献根拠なし、相対倍率のみ校正）。
# 実測比 sadness/shame 最大240倍は 0.4:2.0=5倍に圧縮（brief 不可視・long 恒久化防止の設計判断）。
# FAB (Ritchie 2014, DOI 10.1080/09658211.2014.88413)・睡眠減衰 (Walker & van der Helm 2009,
# DOI 10.1037/a0016570) は「記憶の情動荷重」構成概念につき現在状態減衰に混入させない。
# 再付与時の半減期リセットは意図的仕様（再トリガー=新エピソード開始、Verduyn のエピソード概念準拠）。
# clamp は不採用。LLM 側の過剰再付与は減衰の責務外。
# ⚠ envy/contempt は暫定値 (long 48h, 再校正 2026-09-10 維持判断)。反芻仮説だが、
#   V&L2015 測定値の同族感情 hatred=60h (sadness=120h, joy=35h) が long 帯を支持。
#   medium 格下げの直接証拠なし。再校正トリガー: 反芻(再付与頻度)機構実装時——未到達。
_EMOTION_CATEGORY: dict[str, str] = {
    # brief: V&L2015 最短群 + Scherer1994 最下位
    "surprise": "brief",
    "fear": "brief",
    "disgust": "brief",
    "shame": "brief",
    "relief": "brief",
    # short: Verduyn2011 中央値 9-12分 群相当
    "anger": "short",
    "joy": "short",
    "excitement": "short",
    "frustration": "short",
    "gratitude": "short",
    "awe": "short",
    # medium: 直接データなし感情のデフォルト層
    "anticipation": "medium",
    "trust": "medium",
    "nostalgia": "medium",
    "pride": "medium",
    "contentment": "medium",
    "curiosity": "medium",
    "love": "medium",
    # long: V&L2015 最長 + 反芻駆動群
    "sadness": "long",
    "grief": "long",  # V&L2015 sadness 同群——悲嘆は sadness と同列の最長群
    "loneliness": "long",
    "anxiety": "long",
    "guilt": "long",
    "envy": "long",
    "contempt": "long",
}
_CATEGORY_HALF_LIFE: dict[str, float] = {
    "brief": 9.6,  # ×0.4 — V&L2015 最短群
    "short": 14.4,  # ×0.6 — Verduyn2011 中央値群
    "medium": 24.0,  # ×1.0 — 設計基準値（文献根拠なし）
    "long": 48.0,  # ×2.0 — V&L2015 最長群
}


def resolve_half_life(emotion: str, knob: float | None) -> float:
    """knob 明示時は全体上書き、なければカテゴリテーブル。

    neutral/unknown は knob または 24.0 デフォルト（クラッシュ禁止）。
    """
    if knob is not None:
        return knob
    return _CATEGORY_HALF_LIFE.get(_EMOTION_CATEGORY.get(emotion, ""), 24.0)


def _intensity_factor(intensity: float) -> float:
    """max(0.3, intensity) を切り出しただけ。形式変更はしない。"""
    return max(0.3, intensity)


@dataclass
class EmotionDecayResult:
    """Result of an emotion decay application: before→after state."""

    before_emotion: str
    before_intensity: float
    after_emotion: str
    after_intensity: float
    elapsed_hours: float


def compute_emotion_decay(
    intensity: float,
    elapsed_hours: float,
    half_life_hours: float | None = None,
    emotion: str = "neutral",
    threshold: float | None = None,
    neutral_threshold: float | None = None,
) -> tuple[str, float]:
    """指数減衰で新しい感情強度を計算する。

    減衰係数 = 0.5^(経過時間 / effective_half_life)
    effective_half_life = resolve_half_life(emotion, half_life_hours) * _intensity_factor(intensity)

    Args:
        emotion: 現在の感情ラベル。
        intensity: 現在の強度 [0.0, 1.0]。
        elapsed_hours: 経過時間（時間）。
        half_life_hours: 半減期の上書き値（None ならカテゴリ別テーブル）。
        threshold: 減衰閾値（この差未満なら変化なし、デフォルト 0.005）。
        neutral_threshold: ニュートラル判定閾値（これ未満で neutral に、デフォルト 0.01）。

    Returns:
        (new_emotion, new_intensity) のタプル。
    """
    if threshold is None:
        threshold = 0.005
    if neutral_threshold is None:
        neutral_threshold = 0.01

    if elapsed_hours <= 0 or intensity <= 0.0:
        return emotion, 0.0
    effective_half_life = resolve_half_life(emotion, half_life_hours) * _intensity_factor(intensity)
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
        half_life_hours: 半減期（None なら resolve_half_life のカテゴリテーブル）。
        threshold: 減衰閾値（デフォルト 0.005）。
        neutral_threshold: ニュートラル判定閾値（デフォルト 0.01）。

    Returns:
        EmotionDecayResult if decay was applied, None if no change needed.
    """
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
        intensity=current_intensity,
        elapsed_hours=elapsed_hours,
        half_life_hours=half_life_hours,
        emotion=state.emotion,
        threshold=threshold,
        neutral_threshold=neutral_threshold,
    )
    if new_emotion == state.emotion and abs(new_intensity - current_intensity) < threshold:
        return None

    try:
        result = persona_service.update_emotion(persona, new_emotion, new_intensity, context="time_decay")
        if isinstance(result, Failure):
            logger.warning("EmotionDecay: update_emotion failed: %s", result.error)
            return None
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
    except Exception as e:
        logger.warning("EmotionDecay: unexpected error: %s", e)
    return None
