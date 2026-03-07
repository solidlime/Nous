"""
VOICEVOX HTTP API クライアント。

別 PC または NAS から HTTP で動作する VOICEVOX Engine に接続し、
テキストを WAV バイナリに変換する。

使い方:
    adapter = VoiceAdapter("http://192.168.1.10:50021", speaker_id=3)
    wav = await adapter.speak("興味深いね")
    with open("output.wav", "wb") as f:
        f.write(wav)
"""

import logging
from typing import Optional

import aiohttp

logger = logging.getLogger(__name__)


class VoiceAdapter:
    """VOICEVOX Engine の HTTP API ラッパー。

    POST /audio_query → POST /synthesis の2ステップで
    テキストから WAV バイナリを生成する。

    Args:
        voicevox_url: VOICEVOX Engine の URL（末尾スラッシュなし）。
        speaker_id: 話者 ID（VOICEVOX の /speakers で確認可能）。
        speed_scale: 話速スケール（1.0 = 標準）。
        pitch_scale: ピッチシフト（0.0 = 標準）。
        volume_scale: 音量スケール（1.0 = 標準）。
    """

    def __init__(
        self,
        voicevox_url: str,
        speaker_id: int = 0,
        speed_scale: float = 1.0,
        pitch_scale: float = 0.0,
        volume_scale: float = 1.0,
    ) -> None:
        self._voicevox_url = voicevox_url.rstrip("/")
        self._speaker_id = speaker_id
        self._speed_scale = speed_scale
        self._pitch_scale = pitch_scale
        self._volume_scale = volume_scale

    async def speak(self, text: str) -> Optional[bytes]:
        """テキストを音声合成して WAV バイナリを返す。

        失敗時は None を返す（例外を raise しない）。

        Args:
            text: 音声合成するテキスト。

        Returns:
            WAV バイナリ。失敗時は None。
        """
        try:
            async with aiohttp.ClientSession() as session:
                # Step 1: AudioQuery 生成
                params = {"text": text, "speaker": self._speaker_id}
                async with session.post(
                    f"{self._voicevox_url}/audio_query",
                    params=params,
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    if resp.status != 200:
                        logger.warning(
                            f"VOICEVOX /audio_query 失敗: HTTP {resp.status}"
                        )
                        return None
                    audio_query = await resp.json()

                # カスタムパラメータを適用
                audio_query["speedScale"] = self._speed_scale
                audio_query["pitchScale"] = self._pitch_scale
                audio_query["volumeScale"] = self._volume_scale
                audio_query["outputSamplingRate"] = 24000
                audio_query["outputStereo"] = False

                # Step 2: 音声合成
                async with session.post(
                    f"{self._voicevox_url}/synthesis",
                    params={"speaker": self._speaker_id},
                    json=audio_query,
                    headers={"Content-Type": "application/json"},
                    timeout=aiohttp.ClientTimeout(total=60),
                ) as resp:
                    if resp.status != 200:
                        logger.warning(
                            f"VOICEVOX /synthesis 失敗: HTTP {resp.status}"
                        )
                        return None
                    wav_bytes = await resp.read()
                    logger.debug(
                        f"VOICEVOX 音声合成成功: {len(wav_bytes)} bytes"
                    )
                    return wav_bytes

        except aiohttp.ClientConnectorError:
            logger.warning(
                f"VOICEVOX に接続できない: {self._voicevox_url}"
            )
            return None
        except Exception as e:
            logger.error(f"VOICEVOX 音声合成エラー: {e}", exc_info=True)
            return None

    async def is_available(self) -> bool:
        """VOICEVOX Engine が起動中かどうかを確認する。"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self._voicevox_url}/version",
                    timeout=aiohttp.ClientTimeout(total=5),
                ) as resp:
                    return resp.status == 200
        except Exception:
            return False
