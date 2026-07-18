from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import httpx

from .base import VoiceEngine

if TYPE_CHECKING:
    from nous.config.settings import IrodoriConfig

# 感情 → speed モディファイア
_EMOTION_SPEED: dict[str, float] = {
    "joy": 1.1,
    "sadness": 0.9,
    "anger": 1.2,
}

_DEFAULT_SPEED: float = 1.0
_MAX_RETRIES: int = 3  # 初回 + 2リトライ


class IrodoriEngine(VoiceEngine):
    """Irodori-TTS-Server (OpenAI互換API /v1/audio/speech) を呼ぶ音声合成エンジン。"""

    def __init__(self, config: IrodoriConfig) -> None:
        self._url = config.url.rstrip("/")
        self._voice = config.voice
        self._timeout = httpx.Timeout(config.timeout_seconds)
        self._advanced = config.advanced

    # ── synthesize ────────────────────────────────────────────

    async def synthesize(
        self,
        text: str,
        emotion: str,
        speech_style: str | None = None,  # noqa: ARG002 — 将来の拡張用
        caption: str | None = None,
    ) -> bytes:
        """Irodori-TTS で音声合成しWAVバイト列を返す。

        接続エラーの場合は最大2回リトライする。
        """
        speed = _EMOTION_SPEED.get(emotion, _DEFAULT_SPEED)

        extra_body_irodori: dict = {
            "num_steps": self._advanced.num_steps,
            "cfg_scale_text": self._advanced.cfg_scale_text,
            "cfg_scale_speaker": self._advanced.cfg_scale_speaker,
            "cfg_scale_caption": self._advanced.cfg_scale_caption,
            "chunking_enabled": True,
            "chunk_min_chars": self._advanced.chunk_min_chars,
        }
        if caption:
            extra_body_irodori["caption"] = caption
        if self._advanced.seed is not None:
            extra_body_irodori["seed"] = self._advanced.seed

        payload = {
            "model": "irodori-tts",
            "input": text,
            "voice": self._voice,
            "response_format": "wav",
            "speed": speed,
            "extra_body": {
                "irodori": extra_body_irodori,
            },
        }

        last_exception: Exception | None = None
        for attempt in range(_MAX_RETRIES):
            try:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    resp = await client.post(f"{self._url}/audio/speech", json=payload)
                    resp.raise_for_status()
                    return resp.content
            except (httpx.ConnectError, httpx.TimeoutException) as e:
                last_exception = e
                if attempt < _MAX_RETRIES - 1:
                    await asyncio.sleep(1)
                    continue
                raise RuntimeError(f"Irodori TTS failed after {_MAX_RETRIES} attempts") from last_exception
            except httpx.HTTPStatusError as e:
                # HTTP エラーはリトライしない
                raise RuntimeError(f"Irodori TTS returned HTTP {e.response.status_code}: {e.response.text}") from e

        # ここには到達しない (上で必ず return か raise)
        raise RuntimeError("Unexpected state in IrodoriEngine.synthesize")  # pragma: no cover

    # ── health_check ──────────────────────────────────────────

    async def health_check(self) -> bool:
        """サーバーに疎通確認する (GET /v1/models で確認)。"""
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
                resp = await client.get(f"{self._url}/models")
                return resp.status_code == 200
        except (httpx.ConnectError, httpx.TimeoutException):
            return False
