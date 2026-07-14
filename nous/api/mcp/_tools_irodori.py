"""Irodori TTS tool — voice synthesis via Irodori-TTS-Server."""

from __future__ import annotations

import base64
import json
import logging
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from nous.application.use_cases import AppContext
from nous.domain.chat_config import ChatConfigRepository

logger = logging.getLogger(__name__)

_VOICES_MODEL_TIMEOUT: float = 5.0


async def _tool_irodori_voices(
    ctx: AppContext,
    persona: str,
) -> str:
    """List available voices from Irodori TTS engine.

    Returns JSON with ok:bool, voices (on success) or error message.
    """
    # 1. Get Irodori config — per-persona ChatConfig only
    chat_config = ChatConfigRepository(ctx.connection.get_memory_db()).get(persona)
    enabled = chat_config.irodori_enabled
    if not enabled:
        return json.dumps(
            {"ok": False, "error": "Irodori TTS is not enabled in settings"},
            ensure_ascii=False,
        )

    # 2. Get voice engine config
    config = ctx.settings.irodori

    # 3. Query /v1/models for available voices
    base_url = config.url.rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(_VOICES_MODEL_TIMEOUT)) as client:
            resp = await client.get(f"{base_url}/models")
            resp.raise_for_status()
            models_data = resp.json()
    except Exception as e:
        # Fallback: return configured voice as the only known one
        return json.dumps(
            {
                "ok": True,
                "voices": [{"id": config.voice, "name": config.voice, "source": "config"}],
                "note": f"Could not query server for full list: {e}",
            },
            ensure_ascii=False,
        )

    # 4. Parse models list (OpenAI-compatible format)
    voices: list[dict] = []
    if isinstance(models_data, dict) and "data" in models_data:
        for item in models_data["data"]:
            model_id = item.get("id", "")
            if model_id:
                voices.append({"id": model_id, "name": model_id})
    if not voices:
        voices.append({"id": config.voice, "name": config.voice, "source": "config"})

    return json.dumps({"ok": True, "voices": voices}, ensure_ascii=False)


async def _tool_irodori_tts(
    ctx: AppContext,
    persona: str,
    text: str,
    voice: str | None = None,
    emotion: str | None = None,
) -> str:
    """Synthesize speech via Irodori TTS engine.

    emotion: override persona emotion (joy/sadness/anger/etc).
    If omitted, uses current persona emotion.

    Returns JSON with ok:bool, audio_base64 (on success) or error message.
    """
    # 1. Get Irodori config — per-persona ChatConfig only
    chat_config = ChatConfigRepository(ctx.connection.get_memory_db()).get(persona)
    enabled = chat_config.irodori_enabled
    if not enabled:
        return json.dumps(
            {"ok": False, "error": "Irodori TTS is not enabled in settings"},
            ensure_ascii=False,
        )

    # 2. Get voice engine
    config = ctx.settings.irodori
    from nous.infrastructure.voice.factory import get_voice_engine

    engine = get_voice_engine(config)

    # 3. Override voice if explicitly given
    if voice is not None:
        from nous.infrastructure.voice.irodori import IrodoriEngine

        if isinstance(engine, IrodoriEngine):
            engine._voice = voice  # noqa: SLF001 — dynamic override

    # 4. Health check
    try:
        healthy = await engine.health_check()
        if not healthy:
            return json.dumps(
                {"ok": False, "error": "Irodori TTS server is not available"},
                ensure_ascii=False,
            )
    except Exception as e:
        return json.dumps(
            {"ok": False, "error": f"Health check failed: {e}"},
            ensure_ascii=False,
        )

    # 5. Resolve emotion & speech_style
    speech_style: str | None = None
    if emotion is None:
        emotion = "neutral"
        try:
            state_result = ctx.persona_service.get_context(persona)
            if state_result.is_ok and state_result.value is not None:
                state = state_result.value
                emotion = state.emotion or "neutral"
                speech_style = state.speech_style
        except Exception:
            logger.exception("Failed to get persona state for TTS")

    # 6. Synthesize
    try:
        wav_bytes = await engine.synthesize(
            text=text,
            emotion=emotion,
            speech_style=speech_style,
        )
    except Exception as e:
        return json.dumps(
            {"ok": False, "error": f"Synthesis failed: {e}"},
            ensure_ascii=False,
        )

    # 7. Base64 encode
    audio_b64 = base64.b64encode(wav_bytes).decode("ascii")

    return json.dumps(
        {"ok": True, "audio_base64": audio_b64, "format": "wav"},
        ensure_ascii=False,
    )
