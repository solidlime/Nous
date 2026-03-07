"""
Live2D Web コントローラー。

ブラウザ上の Live2D モデルへの感情パラメータ配信を担う。
api/avatar_routes.py の broadcast_avatar_state() を経由して
全接続 WebSocket クライアントにブロードキャストする。
"""

import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)

# 感情 → Live2D SDK パラメータ マッピング
# (cubism モデル側のパラメータ名に合わせて調整すること)
EMOTION_PARAM_MAP: Dict[str, Dict[str, float]] = {
    "joy": {
        "ParamMouthOpenY": 0.8,
        "ParamEyeLOpen": 1.0,
        "ParamEyeROpen": 1.0,
        "ParamBrowLY": 0.3,
        "ParamBrowRY": 0.3,
    },
    "curiosity": {
        "ParamEyeLOpen": 1.3,
        "ParamEyeROpen": 1.3,
        "ParamBrowLY": 0.6,
        "ParamBrowRY": 0.6,
        "ParamAngleZ": -5.0,
    },
    "boredom": {
        "ParamEyeLOpen": 0.4,
        "ParamEyeROpen": 0.4,
        "ParamMouthOpenY": 0.0,
        "ParamBrowLY": -0.1,
        "ParamBrowRY": -0.1,
    },
    "sadness": {
        "ParamBrowLY": -0.5,
        "ParamBrowRY": -0.5,
        "ParamEyeLOpen": 0.6,
        "ParamEyeROpen": 0.6,
    },
    "anger": {
        "ParamBrowLY": -0.8,
        "ParamBrowRY": -0.8,
        "ParamEyeLOpen": 0.9,
        "ParamEyeROpen": 0.9,
        "ParamMouthOpenY": 0.2,
    },
    "pride": {
        "ParamAngleX": 8.0,
        "ParamEyeLOpen": 0.8,
        "ParamEyeROpen": 0.8,
    },
    "neutral": {
        "ParamEyeLOpen": 1.0,
        "ParamEyeROpen": 1.0,
        "ParamMouthOpenY": 0.1,
        "ParamBrowLY": 0.0,
        "ParamBrowRY": 0.0,
        "ParamAngleX": 0.0,
        "ParamAngleZ": 0.0,
    },
}


class Live2DWebController:
    """api/avatar_routes.py の WebSocket ブロードキャストを制御するクラス。

    EmotionalState を Live2D パラメータ辞書に変換し、
    接続中の全ブラウザクライアントにブロードキャストする。

    Args:
        persona: ペルソナ名（ログ用）。
    """

    def __init__(self, persona: str) -> None:
        self._persona = persona

    def emotion_to_params(
        self,
        emotion: str,
        intensity: float = 1.0,
    ) -> Dict[str, Any]:
        """感情文字列を Live2D パラメータ辞書に変換する。

        Args:
            emotion: 感情名（"joy", "curiosity" 等）。
            intensity: 強度スケール（0.0〜1.0）。パラメータ値に乗算される。

        Returns:
            {"ParamEyeLOpen": 1.3, ...} 形式の辞書。
        """
        base = EMOTION_PARAM_MAP.get(emotion, EMOTION_PARAM_MAP["neutral"])
        return {k: v * intensity for k, v in base.items()}

    async def broadcast_state(self, emotion: str, intensity: float = 1.0) -> None:
        """感情状態を全接続ブラウザに WebSocket でブロードキャストする。

        api/avatar_routes.py の broadcast_avatar_state() を呼び出す。
        接続クライアントがゼロの場合は何もしない。

        Args:
            emotion: 感情名。
            intensity: 強度スケール。
        """
        try:
            from api.avatar_routes import broadcast_avatar_state
            await broadcast_avatar_state({
                "emotion": emotion,
                "intensity": intensity,
                "params": self.emotion_to_params(emotion, intensity),
            })
            logger.debug(
                f"Live2D broadcast: {emotion} (intensity={intensity:.2f}) "
                f"[{self._persona}]"
            )
        except Exception as e:
            logger.warning(f"Live2D ブロードキャスト失敗 [{self._persona}]: {e}")
