"""EmotionDrivenSampler: 感情に基づいてLLM推論温度を動的に調整する。"""

from __future__ import annotations

from typing import Final

# 感情→モディファイア マッピング (RA01)
_EMOTION_MODIFIERS: Final[dict[str, float]] = {
    "anger": 0.15,
    "sadness": -0.10,
    "joy": 0.05,
    "excitement": 0.20,
    "neutral": 0.0,
    "curiosity": 0.05,
    "fear": -0.05,
    "disgust": -0.08,
    "surprise": 0.10,
    "grief": -0.15,
    "love": 0.08,
    "trust": -0.03,
    "anxiety": 0.12,
    "frustration": 0.10,
    "nostalgia": 0.02,
    "pride": 0.03,
    "shame": -0.12,
    "guilt": -0.10,
    "loneliness": -0.08,
    "contentment": -0.05,
    "awe": 0.08,
    "relief": -0.02,
    "envy": 0.05,
    "gratitude": 0.03,
    "contempt": 0.05,
    "anticipation": 0.06,
}

TEMPERATURE_MIN: Final[float] = 0.1
TEMPERATURE_MAX: Final[float] = 1.8


class EmotionDrivenSampler:
    """感情駆動型温度サンプラー。

    ステートレス — 全メソッドは @staticmethod。
    感情の種類と強度から、ベース温度に補正を加える。
    """

    @staticmethod
    def compute(
        base_temp: float,
        emotion: str,
        intensity: float,
        scale: float = 0.2,
    ) -> float:
        """感情に基づき実効温度を計算する。

        Args:
            base_temp: ベース温度 (通常 0.7)。
            emotion: 感情ラベル (大文字小文字は区別しない)。
            intensity: 感情強度 [0.0, 1.0]。
            scale: モディファイア全体スケール係数。

        Returns:
            クランプされた実効温度 [TEMPERATURE_MIN, TEMPERATURE_MAX]。
        """
        modifier = _EMOTION_MODIFIERS.get(emotion.lower(), 0.0)
        effective_modifier = modifier * intensity * scale
        effective_temp = base_temp + effective_modifier
        return max(TEMPERATURE_MIN, min(TEMPERATURE_MAX, effective_temp))
