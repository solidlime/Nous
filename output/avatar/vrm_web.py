"""
Nous VRM Web コントローラー。
ブラウザ埋め込みの Three.js VRM ビューアに感情状態を配信する。

感情名 (Nous 内部) → VRM 1.0 expression 名 のマッピングと
ブロードキャストユーティリティを提供する。
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Nous 感情名 → VRM 1.0 expression preset 名
# @pixiv/three-vrm v2 は VRM 0.x の "Joy"/"Sorrow"/"Fun" を
# VRM 1.0 の "happy"/"sad"/"relaxed" に自動変換するため、
# ここでは VRM 1.0 名を使う。
EMOTION_TO_VRM: dict[str, str] = {
    # Positive
    "joy":         "happy",
    "happy":       "happy",
    "excited":     "happy",
    "pride":       "happy",
    # Curious / Surprised
    "curious":     "surprised",
    "curiosity":   "surprised",
    "surprised":   "surprised",
    "interested":  "surprised",
    # Negative / Sad
    "sad":         "sad",
    "melancholy":  "sad",
    "sorrow":      "sad",
    "lonely":      "sad",
    # Angry
    "angry":       "angry",
    "frustrated":  "angry",
    "annoyed":     "angry",
    # Calm / Relaxed
    "relaxed":     "relaxed",
    "calm":        "relaxed",
    "fun":         "relaxed",
    "content":     "relaxed",
    # Neutral (= 全 expression を 0 にする)
    "neutral":     "neutral",
    "bored":       "neutral",
    "boredom":     "neutral",
}

# 有効な VRM 1.0 標準 expression 名
VRM_EXPRESSIONS = ("happy", "angry", "sad", "relaxed", "surprised")


def emotion_to_vrm_expression(emotion: str) -> tuple[str, float]:
    """感情名を VRM expression 名と推奨強度に変換する。

    Returns:
        (vrm_expression_name, recommended_intensity) のタプル。
        vrm_expression_name が "neutral" の場合は全 expression を 0 にする。
    """
    vrm_name = EMOTION_TO_VRM.get(emotion.lower(), "neutral")
    # 感情の強度: curious/surprised は少し抑えめに、angry は強めに
    intensity_hints = {
        "happy":     0.9,
        "surprised": 0.7,
        "sad":       0.8,
        "angry":     0.9,
        "relaxed":   0.6,
        "neutral":   0.0,
    }
    return vrm_name, intensity_hints.get(vrm_name, 0.8)


class VRMWebController:
    """VRM Web コントローラー。

    感情状態を管理し、WebSocket クライアントへのブロードキャストを担う。
    実際の WebSocket ブロードキャストは api/avatar_routes.py に委譲する。

    Args:
        persona: ペルソナ名。
    """

    def __init__(self, persona: str) -> None:
        self.persona = persona
        self._current_emotion = "neutral"
        self._current_intensity = 0.0
        logger.info(f"VRMWebController initialized for {persona}")

    async def set_emotion(self, emotion: str, intensity: Optional[float] = None) -> None:
        """感情を設定して VRM クライアントにブロードキャストする。

        Args:
            emotion: Nous 内部の感情名。
            intensity: 強度 (0.0-1.0)。None の場合は推奨値を使用。
        """
        vrm_name, default_intensity = emotion_to_vrm_expression(emotion)
        use_intensity = intensity if intensity is not None else default_intensity

        self._current_emotion = emotion
        self._current_intensity = use_intensity

        try:
            from api.avatar_routes import broadcast_vrm_state
            await broadcast_vrm_state(self.persona, {
                "emotion": vrm_name,
                "intensity": use_intensity,
                "source_emotion": emotion,
            })
        except Exception as e:
            logger.warning(f"VRM broadcast failed [{self.persona}]: {e}")

    def get_current_state(self) -> dict:
        """現在の感情状態を返す。"""
        vrm_name, _ = emotion_to_vrm_expression(self._current_emotion)
        return {
            "persona": self.persona,
            "emotion": self._current_emotion,
            "vrm_expression": vrm_name,
            "intensity": self._current_intensity,
        }
