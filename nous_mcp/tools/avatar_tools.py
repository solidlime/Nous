"""
Nous MCP アバター制御ツール。
VTube Studio + Live2D Web の表情制御・音声発話を提供する。
"""

import json
import logging
from typing import Dict, Optional

from nous_mcp.server import get_persona

logger = logging.getLogger(__name__)

# グローバルアダプター参照（main.py で設定する）
_vtube_adapters: Dict[str, any] = {}
_voice_adapters: Dict[str, any] = {}
_live2d_controllers: Dict[str, any] = {}


def register_avatar_adapters(
    vtube: Dict[str, any] = None,
    voice: Dict[str, any] = None,
    live2d: Dict[str, any] = None,
) -> None:
    """main.py からアダプター参照を登録する。"""
    if vtube:
        _vtube_adapters.update(vtube)
    if voice:
        _voice_adapters.update(voice)
    if live2d:
        _live2d_controllers.update(live2d)


def register_avatar_tools(mcp) -> None:
    """FastMCP にアバター制御ツールを登録する。"""

    @mcp.tool()
    async def set_avatar_expression(
        emotion: str,
        intensity: float = 1.0,
    ) -> str:
        """
        アバターの表情を設定する。
        VTube Studio と Live2D Web (ブラウザ) の両方に送信する。

        Args:
            emotion: 感情名 (joy/curiosity/boredom/neutral/melancholy/pride)
            intensity: 強度 (0.0-1.0)
        """
        persona = get_persona()
        results = {}

        vtube = _vtube_adapters.get(persona)
        if vtube:
            try:
                await vtube.set_expression(emotion, intensity)
                results["vtube_studio"] = "ok"
            except Exception as e:
                results["vtube_studio"] = f"error: {e}"

        live2d = _live2d_controllers.get(persona)
        if live2d:
            try:
                from psychology.emotional_model import EmotionalState
                state = EmotionalState(surface_emotion=emotion, surface_intensity=intensity)
                await live2d.broadcast_state(state)
                results["live2d_web"] = "ok"
            except Exception as e:
                results["live2d_web"] = f"error: {e}"

        if not vtube and not live2d:
            return json.dumps({
                "warning": "No avatar adapters configured",
                "emotion": emotion,
                "intensity": intensity,
            }, ensure_ascii=False)

        return json.dumps({"success": True, "emotion": emotion, "intensity": intensity, "results": results}, ensure_ascii=False)

    @mcp.tool()
    async def speak(
        text: str,
    ) -> str:
        """
        VOICEVOX で音声を発話する。
        設定された VOICEVOX サーバーにリクエストを送信し、WAV を生成する。

        Args:
            text: 発話するテキスト
        """
        persona = get_persona()
        voice = _voice_adapters.get(persona)
        if voice is None:
            return json.dumps({
                "error": "VoiceAdapter not configured for this persona",
            }, ensure_ascii=False)
        try:
            wav_bytes = await voice.speak(text)
            if wav_bytes:
                # WAV を一時ファイルに保存してURLを返す
                import tempfile, os
                tmp_dir = os.path.join("data", "tmp")
                os.makedirs(tmp_dir, exist_ok=True)
                tmp_path = os.path.join(tmp_dir, f"voice_{persona}_{_ts()}.wav")
                with open(tmp_path, "wb") as f:
                    f.write(wav_bytes)
                return json.dumps({
                    "success": True,
                    "text": text,
                    "audio_path": tmp_path,
                    "audio_url": f"/data/tmp/{os.path.basename(tmp_path)}",
                }, ensure_ascii=False)
            return json.dumps({"error": "VOICEVOX returned empty audio"}, ensure_ascii=False)
        except Exception as e:
            logger.error(f"speak error: {e}", exc_info=True)
            return json.dumps({"error": str(e)}, ensure_ascii=False)


def _ts() -> str:
    from datetime import datetime
    return datetime.now().strftime("%Y%m%d%H%M%S")
