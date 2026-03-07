"""
VTube Studio WebSocket API クライアント。

VTube Studio のプラグイン API（ポート 8001）に接続し、
感情状態に対応する Live2D パラメータをリアルタイムで更新する。

参考: https://github.com/DenchiSoft/VTubeStudio
"""

import json
import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# 感情 → VTube Studio パラメータ マッピング
EMOTION_PARAMS: Dict[str, Dict[str, float]] = {
    "joy": {
        "FaceAngleX": 5.0,
        "MouthOpenY": 0.7,
        "EyeOpenLeft": 1.0,
        "EyeOpenRight": 1.0,
        "BrowLeftY": 0.2,
        "BrowRightY": 0.2,
    },
    "curiosity": {
        "EyeOpenLeft": 1.2,
        "EyeOpenRight": 1.2,
        "BrowLeftY": 0.5,
        "BrowRightY": 0.5,
        "FaceAngleZ": -5.0,
    },
    "boredom": {
        "EyeOpenLeft": 0.4,
        "EyeOpenRight": 0.4,
        "MouthOpenY": 0.05,
        "BrowLeftY": -0.1,
        "BrowRightY": -0.1,
    },
    "sadness": {
        "BrowLeftY": -0.5,
        "BrowRightY": -0.5,
        "EyeOpenLeft": 0.6,
        "EyeOpenRight": 0.6,
        "MouthOpenY": 0.1,
        "FaceAngleX": -3.0,
    },
    "anger": {
        "BrowLeftY": -0.8,
        "BrowRightY": -0.8,
        "EyeOpenLeft": 0.9,
        "EyeOpenRight": 0.9,
        "MouthOpenY": 0.3,
    },
    "pride": {
        "FaceAngleX": 8.0,
        "EyeOpenLeft": 0.8,
        "EyeOpenRight": 0.8,
        "BrowLeftY": 0.1,
        "BrowRightY": 0.1,
    },
    "neutral": {
        "EyeOpenLeft": 1.0,
        "EyeOpenRight": 1.0,
        "MouthOpenY": 0.0,
        "BrowLeftY": 0.0,
        "BrowRightY": 0.0,
        "FaceAngleX": 0.0,
        "FaceAngleZ": 0.0,
    },
}


class VTubeStudioAdapter:
    """VTube Studio WebSocket API ラッパー。

    感情文字列を受け取って対応するパラメータを VTube Studio に送信する。
    接続・認証は lazy（最初の操作時）に行う。

    Args:
        ws_url: VTube Studio WebSocket URL（例: "ws://localhost:8001"）。
        plugin_name: VTube Studio プラグイン名（ユーザーが承認するダイアログに表示される）。
    """

    def __init__(self, ws_url: str, plugin_name: str = "Nous") -> None:
        self._ws_url = ws_url
        self._plugin_name = plugin_name
        self._ws = None
        self._authenticated = False

    async def connect(self) -> bool:
        """VTube Studio に接続してプラグイン認証を行う。

        Returns:
            接続・認証成功なら True。
        """
        try:
            import websockets
            self._ws = await websockets.connect(self._ws_url)

            # プラグイン認証リクエスト
            auth_req = {
                "apiName": "VTubeStudioPublicAPI",
                "apiVersion": "1.0",
                "requestID": "nous_auth_req",
                "messageType": "AuthenticationRequest",
                "data": {
                    "pluginName": self._plugin_name,
                    "pluginDeveloper": "Nous",
                    "authenticationToken": "",
                },
            }
            await self._ws.send(json.dumps(auth_req))
            raw = await self._ws.recv()
            resp = json.loads(raw)

            if resp.get("messageType") == "AuthenticationResponse":
                self._authenticated = True
                logger.info(f"VTubeStudio 接続・認証成功: {self._ws_url}")
                return True

            logger.warning(f"VTubeStudio 認証失敗: {resp}")
            return False

        except ImportError:
            logger.warning("websockets パッケージが見つからない。pip install websockets")
            return False
        except Exception as e:
            logger.warning(f"VTubeStudio 接続失敗: {e}")
            self._ws = None
            self._authenticated = False
            return False

    async def set_expression(self, emotion: str, intensity: float = 1.0) -> None:
        """感情に対応するパラメータを VTube Studio に送信する。

        Args:
            emotion: 感情名（"joy", "curiosity", "boredom", etc.）。
            intensity: 強度スケール（0.0〜1.0）。
        """
        if not self._authenticated:
            ok = await self.connect()
            if not ok:
                return

        params = EMOTION_PARAMS.get(emotion, EMOTION_PARAMS["neutral"])
        for param_id, value in params.items():
            await self._set_parameter(param_id, value * intensity)

    async def _set_parameter(self, param_id: str, value: float) -> None:
        """単一パラメータを VTube Studio に送信する。"""
        if self._ws is None:
            return
        request = {
            "apiName": "VTubeStudioPublicAPI",
            "apiVersion": "1.0",
            "requestID": f"set_{param_id}",
            "messageType": "InjectParameterDataRequest",
            "data": {
                "parameterValues": [
                    {"id": param_id, "value": float(value)}
                ]
            },
        }
        try:
            await self._ws.send(json.dumps(request))
        except Exception as e:
            logger.warning(f"VTubeStudio パラメータ設定失敗 [{param_id}]: {e}")
            self._authenticated = False
            self._ws = None

    async def trigger_hotkey(self, hotkey_id: str) -> None:
        """VTube Studio のホットキーを発火する。

        Args:
            hotkey_id: VTube Studio で設定されたホットキー ID。
        """
        if not self._authenticated:
            await self.connect()
        if self._ws is None:
            return

        request = {
            "apiName": "VTubeStudioPublicAPI",
            "apiVersion": "1.0",
            "requestID": "nous_hotkey",
            "messageType": "HotkeyTriggerRequest",
            "data": {"hotkeyID": hotkey_id},
        }
        try:
            await self._ws.send(json.dumps(request))
            logger.debug(f"VTubeStudio ホットキー発火: {hotkey_id}")
        except Exception as e:
            logger.warning(f"VTubeStudio ホットキー失敗: {e}")
