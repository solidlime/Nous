"""Irodori TTS tool — voice synthesis via Irodori-TTS-Server."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nous.application.use_cases import AppContext
from nous.domain.chat_config import ChatConfigRepository

logger = logging.getLogger(__name__)


async def _tool_irodori_tts(
    ctx: AppContext,
    persona: str,
    text: str,
    voice: str | None = None,
) -> str:
    """Synthesize speech via Irodori TTS engine.

    Returns JSON with ok:bool, audio_base64 (on success) or error message.
    """
    # 1. Get Irodori config — ChatConfig with fallback to Settings
    chat_config = ChatConfigRepository(ctx.connection.get_memory_db()).get(persona)
    config = ctx.settings.irodori
    enabled = chat_config.irodori_enabled or config.enabled
    if not enabled:
        return json.dumps(
            {"ok": False, "error": "Irodori TTS is not enabled in settings"},
            ensure_ascii=False,
        )

    # 2. Get voice engine
    from nous.infrastructure.voice.factory import get_voice_engine

    engine = get_voice_engine(config)
    if engine is None:
        return json.dumps(
            {"ok": False, "error": "Failed to create voice engine"},
            ensure_ascii=False,
        )

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

    # 5. Get persona state (for emotion / speech_style)
    emotion = "neutral"
    speech_style: str | None = None
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
    import base64

    audio_b64 = base64.b64encode(wav_bytes).decode("ascii")

    return json.dumps(
        {"ok": True, "audio_base64": audio_b64, "format": "wav"},
        ensure_ascii=False,
    )
