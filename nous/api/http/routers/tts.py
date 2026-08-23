from __future__ import annotations

import base64
import hashlib
import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from starlette.responses import FileResponse, JSONResponse, Response

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

        from nous.config.settings import get_settings
        from nous.domain.chat_config import ChatConfigFileRepository

        chat_config = ChatConfigFileRepository(get_settings().data_root).get(persona)
        irodori_config = _get_irodori_config(ctx, chat_config)
        engine = get_voice_engine(irodori_config)

        # health check
        try:
            ok = await engine.health_check()
            if not ok:
                return JSONResponse({"ok": False, "error": "Voice engine health check failed"}, status_code=503)
        # TTSエンジン未起動時の早期リターン
        except Exception:
            return JSONResponse({"ok": False, "error": "Voice engine unreachable"}, status_code=503)

        # parse request body
        try:
            body = await request.json()
        except (json.JSONDecodeError, TypeError):
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
        emotion = "neutral"
        caption: str | None = None
        state = None
        if chat_config.voice_emotion_link:
            state_result = ctx.persona_service.get_context(persona)
            if state_result.is_ok and state_result.value:
                state = state_result.value
                emotion = state.emotion or "neutral"

                # Build simple context caption (always, even if LLM is enabled — as fallback)
                intensity_pct = int((state.emotion_intensity or 0.0) * 100)
                caption_parts = [f"{emotion}{intensity_pct}%"]
                if state.relationship_status:
                    caption_parts.append(f"Relationship: {state.relationship_status}")
                if state.appearance:
                    caption_parts.append(f"Appearance: {state.appearance}")
                if state.environment:
                    caption_parts.append(f"Environment: {state.environment}")
                caption = "\n".join(caption_parts)

        # LLM caption generation (when enabled, overrides simple context injection)
        irodori_caption_llm_enabled = getattr(chat_config, "irodori_caption_llm_enabled", False)
        if irodori_caption_llm_enabled and state:
            try:
                # Get LLM config from chat config
                provider_name = getattr(chat_config, "provider", "opencode_go")
                api_key = getattr(chat_config, "api_key", "")
                model_name = getattr(chat_config, "irodori_caption_llm_model", "") or getattr(chat_config, "model", "")
                base_url = getattr(chat_config, "base_url", "")

                from nous.infrastructure.llm.factory import get_provider

                provider = get_provider(provider_name, api_key, model_name, base_url)

                # Build voice-relevant context
                voice_context_parts = []
                if state:
                    if state.emotion and state.emotion != "neutral":
                        voice_context_parts.append(
                            f"感情: {state.emotion} (強度: {int((state.emotion_intensity or 0.0) * 10)}/10)"
                        )
                    voice_related = []
                    if state.relationship_status:
                        voice_related.append(f"相手との関係: {state.relationship_status}")
                    if state.appearance:
                        voice_related.append(f"外見・雰囲気: {state.appearance}")
                    if state.environment:
                        voice_related.append(f"環境: {state.environment}")
                    if voice_related:
                        voice_context_parts.append("\n".join(voice_related))
                voice_context = "\n".join(voice_context_parts) if voice_context_parts else "（特になし）"

                llm_system = """あなたは音声合成（irodori-tts）向けキャプション生成AIです。
読み上げテキストの内容と話者の状況から、話者の声質・感情・話し方を自然な日本語1文で記述してください。

## 含めるべき要素（該当するもののみ）
- 声の高さ・速さ・質感（落ち着いた/高い/ハスキー/ささやく 等）
- 感情の種類と強度（嬉しそう/怒り/悲しみ/驚き 等）
- 話し方のスタイル（丁寧/カジュアル/近い距離感/遠い距離感）
- 発話の特徴（震え/息遣い/間/たどたどしさ 等）

## 例
- 「落ち着いた女性の声で、近い距離感でやわらかく自然に読み上げてください。」
- 「深く傷つき、今にも泣き出しそうな様子。声が震えており、悲痛なトーンで弱々しく話す。」
- 「余裕のある大人の男性。親しい相手に対して、くだけた雰囲気で呆れながらも楽しそうに話している。」

## 制約
- 80文字以内の自然な日本語1文
- 話者情報が提供された場合は必ず反映する
- 読み上げテキスト自体の内容から感情を推測して良い
- 説明文ではなく「〜話す」「〜読み上げる」で締める
- 出力はキャプションの本文のみ（JSONや説明は不要）"""

                llm_user = f"""## 話者情報
{voice_context}

## 読み上げテキスト
{text}"""

                from nous.infrastructure.llm.base import ErrorEvent, LLMMessage, TextDeltaEvent

                full_content: list[str] = []
                async for event in provider.stream(
                    messages=[LLMMessage(role="user", content=llm_user)],
                    system=llm_system,
                    temperature=0.7,
                    max_tokens=256,
                ):
                    if isinstance(event, TextDeltaEvent):
                        full_content.append(event.content)
                    elif isinstance(event, ErrorEvent):
                        logger.warning("LLM caption generation error: %s", event.message)
                        break
                llm_caption = "".join(full_content).strip()
                if llm_caption:
                    caption = llm_caption
                    logger.info("LLM caption generated for TTS: %s", llm_caption[:100])
            except Exception:
                logger.exception("LLM caption generation failed, falling back to context injection")

        # ---- TTS audio cache ----
        voice_speed = getattr(chat_config, "voice_speed", 1.0)
        from nous.config.settings import get_settings

        settings = get_settings()
        cache_dir = Path(settings.data_root) / "persona" / persona / "tts_cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_key = hashlib.sha256(f"{text}|{emotion}|{caption or ''}|{voice_speed}".encode()).hexdigest()
        hash12 = cache_key[:12]
        new_filename = f"{hash12}.wav"
        new_cache_path = cache_dir / new_filename

        # Backward-compatible cache lookup: try new format first, then glob old format
        found_path = None
        audio_url_filename = new_filename
        if new_cache_path.exists():
            found_path = new_cache_path
        else:
            matches = sorted(cache_dir.glob(f"{hash12}*.wav"))
            if matches:
                found_path = matches[0]
                audio_url_filename = found_path.name
        audio_url = f"/api/tts/{persona}/cache/{audio_url_filename}"

        if found_path:
            audio_bytes = found_path.read_bytes()
            logger.debug("TTS cache HIT: %s", found_path)
            return JSONResponse(
                {
                    "ok": True,
                    "audio_base64": base64.b64encode(audio_bytes).decode("ascii"),
                    "audio_url": audio_url,
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
            new_cache_path.write_bytes(audio_bytes)
            logger.debug("TTS cache MISS: %s", new_cache_path)
            return JSONResponse(
                {
                    "ok": True,
                    "audio_base64": base64.b64encode(audio_bytes).decode("ascii"),
                    "audio_url": audio_url,
                    "format": "wav",
                }
            )
        except Exception:
            return JSONResponse({"ok": False, "error": "Voice synthesis failed"}, status_code=500)

    @mcp.custom_route("/api/tts/{persona}/voices", methods=["GET"])
    async def list_voices(request: Request) -> JSONResponse:
        """List available TTS voices for a persona (TE04)."""
        persona = _resolve_persona_from_request(request)
        ctx = _safe_get_context(persona)
        if not ctx:
            return JSONResponse({"ok": False, "error": "Persona not found"}, status_code=404)

        from nous.config.settings import get_settings
        from nous.domain.chat_config import ChatConfigFileRepository

        chat_config = ChatConfigFileRepository(get_settings().data_root).get(persona)
        irodori_config = _get_irodori_config(ctx, chat_config)

        # Query the Irodori TTS server for available models
        import httpx

        base_url = irodori_config.url.rstrip("/")
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
                resp = await client.get(f"{base_url}/v1/models")
                resp.raise_for_status()
                models_data = resp.json()
        # 音声一覧取得失敗時のフォールバック
        except Exception:
            # Fallback: return configured voice as the only known one
            return JSONResponse(
                {
                    "ok": True,
                    "voices": [{"id": irodori_config.voice, "name": irodori_config.voice, "source": "config"}],
                    "note": "Could not query server for voice list",
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

        from nous.config.settings import get_settings
        from nous.domain.chat_config import ChatConfigFileRepository

        chat_config = ChatConfigFileRepository(get_settings().data_root).get(persona)
        irodori_config = _get_irodori_config(ctx, chat_config)
        base_url = irodori_config.url.rstrip("/")

        import httpx

        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
                resp = await client.get(f"{base_url}/v1/models")
                models_data = resp.json() if resp.status_code == 200 else None
                models = []
                if models_data and isinstance(models_data, dict) and "data" in models_data:
                    for item in models_data["data"]:
                        mid = item.get("id", "")
                        if mid:
                            models.append({"id": mid, "name": mid})
                return JSONResponse(
                    {
                        "ok": True,
                        "connected": True,
                        "url": base_url,
                        "models": models,
                    }
                )
        except Exception:
            return JSONResponse(
                {
                    "ok": True,
                    "connected": False,
                    "url": base_url,
                    "error": "Connection check failed",
                }
            )

    @mcp.custom_route("/api/tts/{persona}/cache/{filename}", methods=["GET"])
    async def serve_tts_cache(request: Request) -> Response:
        """Serve cached TTS audio from memory storage."""
        import mimetypes
        import os

        persona = _resolve_persona_from_request(request)
        filename = request.path_params.get("filename", "")
        safe_name = os.path.basename(filename).replace("..", "").strip()
        if not safe_name or not safe_name.lower().endswith(".wav"):
            return JSONResponse({"error": "Invalid filename"}, status_code=400)

        from nous.config.settings import get_settings

        settings = get_settings()
        file_path = Path(settings.data_root) / "persona" / persona / "tts_cache" / safe_name
        if not file_path.exists():
            return JSONResponse({"error": "File not found"}, status_code=404)

        mime_type, _ = mimetypes.guess_type(safe_name)
        mime_type = mime_type or "audio/wav"
        return FileResponse(str(file_path), media_type=mime_type)

    @mcp.custom_route("/api/tts/{persona}/cache/{filename}", methods=["DELETE"])
    async def delete_tts_cache(request: Request) -> JSONResponse:
        """Delete a cached TTS audio file. Idempotent — returns deleted:false if not found."""
        import os

        persona = _resolve_persona_from_request(request)
        filename = request.path_params.get("filename", "")
        safe_name = os.path.basename(filename).replace("..", "").strip()
        if not safe_name or not safe_name.lower().endswith(".wav"):
            return JSONResponse({"ok": False, "error": "Invalid filename"}, status_code=400)

        from nous.config.settings import get_settings

        settings = get_settings()
        file_path = Path(settings.data_root) / "persona" / persona / "tts_cache" / safe_name
        if not file_path.exists():
            return JSONResponse({"ok": True, "deleted": False})

        file_path.unlink()
        return JSONResponse({"ok": True, "deleted": True})
