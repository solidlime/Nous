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


class IrodoriEngine(VoiceEngine):
    """Irodori-TTS-Server (OpenAI互換API /v1/audio/speech) を呼ぶ音声合成エンジン。"""

    def __init__(self, config: IrodoriConfig) -> None:
        self._url = config.url.rstrip("/")
        self._voice = config.voice
        self._timeout = httpx.Timeout(config.timeout_seconds)
        self._health_timeout = httpx.Timeout(config.health_timeout_seconds)
        self._retry_count = config.retry_count
        self._advanced = config.advanced

    def set_voice(self, voice: str) -> None:
        """リクエスト単位のボイス上書き。設定ファイルには書き戻さない。"""
        self._voice = voice

    # ── synthesize ────────────────────────────────────────────

    def _build_payload(self, text, emotion, caption, speed, *, stream: bool = False) -> dict:
        speed = round(speed if speed is not None else _EMOTION_SPEED.get(emotion, _DEFAULT_SPEED), 2)
        irodori_opts: dict = {
            "num_steps": self._advanced.num_steps,
            "cfg_scale_text": self._advanced.cfg_scale_text,
            "cfg_scale_speaker": self._advanced.cfg_scale_speaker,
            "cfg_scale_caption": self._advanced.cfg_scale_caption,
            "chunking_enabled": True,
            "chunk_min_chars": self._advanced.chunk_min_chars,
        }
        if caption:
            irodori_opts["caption"] = caption
        if self._advanced.seed is not None and self._advanced.seed != 0:
            irodori_opts["seed"] = self._advanced.seed
        payload = {
            "model": "irodori-tts",
            "input": text,
            "voice": self._voice,
            "response_format": "wav",
            "speed": speed,
            "irodori": irodori_opts,
        }
        if stream:
            payload["stream_format"] = "sse"
            irodori_opts["first_sentence_chunk_min_chars"] = self._advanced.first_sentence_chunk_min_chars
        return payload

    async def synthesize(
        self,
        text: str,
        emotion: str,
        caption: str | None = None,
        speed: float | None = None,
    ) -> bytes:
        """Irodori-TTS で音声合成しWAVバイト列を返す。

        接続エラーの場合は settings.irodori.retry_count まで試行する。
        """
        # float 演算の誤差 (1.1000000000000001 等) を防ぐため2桁に丸めてから送信
        # Irodori-TTS-Server の SpeechRequest はトップレベル "irodori" を見る。
        # "extra_body" ネストは extra="allow" で黙殺されるため使わない。
        payload = self._build_payload(text, emotion, caption, speed)

        last_exception: Exception | None = None
        for attempt in range(self._retry_count):
            try:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    resp = await client.post(f"{self._url}/v1/audio/speech", json=payload)
                    resp.raise_for_status()
                    return resp.content
            except (httpx.ConnectError, httpx.TimeoutException) as e:
                last_exception = e
                if attempt < self._retry_count - 1:
                    await asyncio.sleep(1)
                    continue
                raise RuntimeError(f"Irodori TTS failed after {self._retry_count} attempts") from last_exception
            except httpx.HTTPStatusError as e:
                # HTTP エラーはリトライしない
                raise RuntimeError(f"Irodori TTS returned HTTP {e.response.status_code}: {e.response.text}") from e

        # ここには到達しない (上で必ず return か raise)
        raise RuntimeError("Unexpected state in IrodoriEngine.synthesize")  # pragma: no cover

    async def stream_speech(
        self,
        text: str,
        emotion: str,
        caption: str | None = None,
        speed: float | None = None,
    ):
        """SSEで合成し、audioチャンク（完結wav bytes）ごとにyieldする。単発・リトライなし。"""
        import base64
        import binascii
        import json

        payload = self._build_payload(text, emotion, caption, speed, stream=True)
        timeout = httpx.Timeout(10.0, read=180.0, write=10.0, pool=10.0)
        try:
            async with (
                httpx.AsyncClient(timeout=timeout) as client,
                client.stream("POST", f"{self._url}/v1/audio/speech", json=payload) as resp,
            ):
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    try:
                        evt = json.loads(line[5:].strip())
                    except ValueError:
                        continue
                    if not isinstance(evt, dict):
                        continue
                    b64 = evt.get("audio_base64") or evt.get("audio_b64") or evt.get("audio")
                    if isinstance(b64, str) and b64:
                        try:
                            yield base64.b64decode(b64, validate=True)
                        except (ValueError, binascii.Error):
                            continue
                    etype = str(evt.get("type") or evt.get("event") or "")
                    if etype in ("done", "error", "end", "complete"):
                        break
        except httpx.HTTPStatusError as e:
            raise RuntimeError(f"Irodori TTS stream HTTP {e.response.status_code}") from e
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            raise RuntimeError("Irodori TTS stream failed") from e

    # ── health_check ──────────────────────────────────────────

    async def _get_models_response(self) -> httpx.Response | None:
        """GET /v1/models。接続系エラーは None（health_check / fetch_models 共通）。"""
        try:
            async with httpx.AsyncClient(timeout=self._health_timeout) as client:
                return await client.get(f"{self._url}/v1/models")
        except httpx.HTTPError:
            return None

    async def health_check(self) -> bool:
        """サーバーに疎通確認する (GET /v1/models で確認)。"""
        resp = await self._get_models_response()
        return resp is not None and resp.status_code == 200

    async def fetch_models(self) -> list[dict] | None:
        """GET /v1/models のモデル一覧。未接続・非 200 は None（health_check と同じ判定）。"""
        resp = await self._get_models_response()
        if resp is None or resp.status_code != 200:
            return None
        try:
            data = resp.json()
        except ValueError:
            return []
        items = data.get("data") if isinstance(data, dict) else None
        if not isinstance(items, list):
            return []
        return [{"id": mid, "name": mid} for item in items if isinstance(item, dict) and (mid := item.get("id"))]
