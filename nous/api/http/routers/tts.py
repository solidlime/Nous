from __future__ import annotations

import base64
import hashlib
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from starlette.responses import JSONResponse

from nous.api.http.deps import _resolve_persona_from_request, _safe_get_context
from nous.infrastructure.voice.factory import get_voice_engine

if TYPE_CHECKING:
    from starlette.requests import Request

    from nous.config.settings import IrodoriConfig

logger = logging.getLogger(__name__)


def _get_irodori_config(ctx, chat_config) -> IrodoriConfig:
    """Build IrodoriConfig from ChatConfig.voice_url if set, else global settings."""
    from nous.config.settings import IrodoriAdvancedParams, IrodoriConfig

    global_config = ctx.settings.irodori
    # Build advanced params from ChatConfig
    advanced = IrodoriAdvancedParams(
        num_steps=getattr(chat_config, "irodori_num_steps", 30),
        cfg_scale_text=getattr(chat_config, "irodori_cfg_scale_text", 3.2),
        cfg_scale_speaker=getattr(chat_config, "irodori_cfg_scale_speaker", 5.0),
        cfg_scale_caption=getattr(chat_config, "irodori_cfg_scale_caption", 4.2),
        chunk_min_chars=getattr(chat_config, "irodori_chunk_min_chars", 85),
        seed=getattr(chat_config, "irodori_seed", None),
    )
    return IrodoriConfig(
        url=chat_config.voice_url or global_config.url,
        voice=chat_config.voice_model or global_config.voice,
        model=global_config.model,
        timeout_seconds=global_config.timeout_seconds,
        advanced=advanced,
    )


def register_tts_routes(mcp) -> None:
    @mcp.custom_route("/api/tts/{persona}", methods=["POST"])
    async def synthesize_tts(request: Request) -> JSONResponse:
        persona = _resolve_persona_from_request(request)
        ctx = _safe_get_context(persona)
        if not ctx:
            return JSONResponse({"ok": False, "error": "Persona not found"}, status_code=404)

        from nous.domain.chat_config import ChatConfigRepository

        chat_config = ChatConfigRepository(ctx.connection.get_memory_db()).get(persona)
        irodori_config = _get_irodori_config(ctx, chat_config)
        engine = get_voice_engine(irodori_config)

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

        # Optional voice override (body > chat_config.voice_model > global)
        voice_override = body.get("voice") or (chat_config.voice_model or None)
        if voice_override:
            from nous.infrastructure.voice.irodori import IrodoriEngine

            if isinstance(engine, IrodoriEngine):
                engine._voice = voice_override  # noqa: SLF001

        # get persona state for emotion + build caption
        # Caption format: {emotion}{intensity}%\nPhysical: ...\nMental: ...
        emotion = "neutral"
        caption: str | None = None
        if chat_config.voice_emotion_link:
            state_result = ctx.persona_service.get_context(persona)
            if state_result.is_ok and state_result.value:
                state = state_result.value
                emotion = state.emotion or "neutral"
                intensity_pct = int((state.emotion_intensity or 0.0) * 100)
                caption_parts = [f"{emotion}{intensity_pct}%"]
                # Read one-shot physical/mental from memories (tags)
                import datetime as _dt

                for tag_name, label in [("physical_state", "Physical"), ("mental_state", "Mental")]:
                    mems_result = ctx.memory_service.get_by_tags([tag_name])
                    if mems_result.is_ok and mems_result.value:
                        latest = max(mems_result.value, key=lambda m: m.created_at or _dt.datetime.min)
                        content = latest.content
                        prefix = f"{tag_name}: "
                        if content.startswith(prefix):
                            content = content[len(prefix) :]
                        if content.strip():
                            caption_parts.append(f"{label}: {content}")
                caption = "\n".join(caption_parts)

        # ---- TTS audio cache ----
        voice_speed = getattr(chat_config, "voice_speed", 1.0)
        from nous.config.settings import get_settings
        settings = get_settings()
        cache_dir = Path(settings.data_root) / "memory" / persona / "tts_cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_key = hashlib.sha256(f"{text}|{emotion}|{caption or ''}|{voice_speed}".encode()).hexdigest()
        cache_path = cache_dir / f"{cache_key}.wav"

        if cache_path.exists():
            audio_bytes = cache_path.read_bytes()
            logger.debug("TTS cache HIT: %s", cache_path)
            return JSONResponse(
                {
                    "ok": True,
                    "audio_base64": base64.b64encode(audio_bytes).decode("ascii"),
                    "format": "wav",
                }
            )

        try:
            audio_bytes = await engine.synthesize(
                text=text,
                emotion=emotion,
                caption=caption,
                speed=None if voice_speed == 1.0 else voice_speed,
            )
            cache_path.write_bytes(audio_bytes)
            logger.debug("TTS cache MISS: %s", cache_path)
            return JSONResponse(
                {
                    "ok": True,
                    "audio_base64": base64.b64encode(audio_bytes).decode("ascii"),
                    "format": "wav",
                }
            )
        except Exception as e:
            return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

    @mcp.custom_route("/api/tts/{persona}/voices", methods=["GET"])
    async def list_voices(request: Request) -> JSONResponse:
        """List available TTS voices for a persona (TE04)."""
        persona = _resolve_persona_from_request(request)
        ctx = _safe_get_context(persona)
        if not ctx:
            return JSONResponse({"ok": False, "error": "Persona not found"}, status_code=404)

        from nous.domain.chat_config import ChatConfigRepository

        chat_config = ChatConfigRepository(ctx.connection.get_memory_db()).get(persona)
        irodori_config = _get_irodori_config(ctx, chat_config)

        # Query the Irodori TTS server for available models
        import httpx

        base_url = irodori_config.url.rstrip("/")
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
                resp = await client.get(f"{base_url}/models")
                resp.raise_for_status()
                models_data = resp.json()
        except Exception as e:
            # Fallback: return configured voice as the only known one
            return JSONResponse(
                {
                    "ok": True,
                    "voices": [{"id": irodori_config.voice, "name": irodori_config.voice, "source": "config"}],
                    "note": f"Could not query server: {e}",
                }
            )

        # Parse models list (OpenAI-compatible format)
        voices: list[dict] = []
        if isinstance(models_data, dict) and "data" in models_data:
            for item in models_data["data"]:
                model_id = item.get("id", "")
                if model_id:
                    voices.append({"id": model_id, "name": model_id})
        if not voices:
            voices.append({"id": irodori_config.voice, "name": irodori_config.voice, "source": "config"})

        return JSONResponse({"ok": True, "voices": voices})

    @mcp.custom_route("/api/tts/{persona}/health", methods=["GET"])
    async def health_check_tts(request: Request) -> JSONResponse:
        persona = _resolve_persona_from_request(request)
        ctx = _safe_get_context(persona)
        if not ctx:
            return JSONResponse({"ok": True, "connected": False, "error": "Persona not found"}, status_code=404)

        from nous.domain.chat_config import ChatConfigRepository

        chat_config = ChatConfigRepository(ctx.connection.get_memory_db()).get(persona)
        irodori_config = _get_irodori_config(ctx, chat_config)
        base_url = irodori_config.url.rstrip("/")

        import httpx

        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
                resp = await client.get(f"{base_url}/models")
                models_data = resp.json() if resp.status_code == 200 else None
                models = []
                if models_data and isinstance(models_data, dict) and "data" in models_data:
                    for item in models_data["data"]:
                        mid = item.get("id", "")
                        if mid:
                            models.append({"id": mid, "name": mid})
                return JSONResponse({
                    "ok": True,
                    "connected": True,
                    "url": base_url,
                    "models": models,
                })
        except Exception as e:
            return JSONResponse({
                "ok": True,
                "connected": False,
                "url": base_url,
                "error": str(e),
            })
