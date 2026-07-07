from __future__ import annotations

import base64
import logging
from typing import TYPE_CHECKING

from starlette.responses import JSONResponse

from nous.api.http.deps import _resolve_persona_from_request, _safe_get_context
from nous.infrastructure.voice.factory import get_voice_engine

if TYPE_CHECKING:
    from starlette.requests import Request

logger = logging.getLogger(__name__)


def register_tts_routes(mcp) -> None:
    @mcp.custom_route("/api/tts/{persona}", methods=["POST"])
    async def synthesize_tts(request: Request) -> JSONResponse:
        persona = _resolve_persona_from_request(request)
        ctx = _safe_get_context(persona)
        if not ctx:
            return JSONResponse({"ok": False, "error": "Persona not found"}, status_code=404)

        irodori_config = ctx.settings.irodori
        if not irodori_config.enabled:
            return JSONResponse({"ok": False, "error": "TTS not enabled"}, status_code=400)

        engine = get_voice_engine(irodori_config)
        if engine is None:
            return JSONResponse({"ok": False, "error": "No voice engine available"}, status_code=503)

        # health check
        try:
            ok = await engine.health_check()
            if not ok:
                return JSONResponse({"ok": False, "error": "Voice engine health check failed"}, status_code=503)
        except Exception:
            return JSONResponse({"ok": False, "error": "Voice engine unreachable"}, status_code=503)

        # parse request body
        try:
            body = await request.json()
        except Exception:
            body = {}
        text = body.get("text", "")
        if not text:
            return JSONResponse({"ok": False, "error": "text is required"}, status_code=400)

        # get persona state for emotion
        state_result = ctx.persona_service.get_context(persona)
        emotion = "neutral"
        speech_style = None
        if state_result.is_ok and state_result.value:
            emotion = state_result.value.emotion or "neutral"
            speech_style = state_result.value.speech_style

        try:
            audio_bytes = await engine.synthesize(
                text=text,
                emotion=emotion,
                speech_style=speech_style,
            )
            return JSONResponse(
                {
                    "ok": True,
                    "audio_base64": base64.b64encode(audio_bytes).decode("ascii"),
                    "format": "wav",
                }
            )
        except Exception as e:
            return JSONResponse({"ok": False, "error": str(e)}, status_code=500)
