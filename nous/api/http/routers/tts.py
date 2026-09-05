from __future__ import annotations

import base64
import hashlib
import json
import logging
import math
from pathlib import Path
from typing import TYPE_CHECKING

from starlette.responses import FileResponse, JSONResponse, Response

from nous.api.http.deps import _PERSONA_PATTERN, _resolve_persona_from_request, _safe_get_context
from nous.infrastructure.voice.factory import get_voice_engine

if TYPE_CHECKING:
    from starlette.requests import Request

    from nous.config.settings import IrodoriConfig

logger = logging.getLogger(__name__)


EMOTION_TONE_HINTS: dict[str, str] = {
    "joy": "明るく弾んだ、声のトーンが上がった話し方で",
    "sadness": "落ち着いた、やや低くゆっくりした話し方で",
    "anger": "強く短く、勢いのある話し方で",
    "surprise": "間と抑揚を大きく、驚きを含んだ話し方で",
    "fear": "小さく震える、不安を含んだ話し方で",
    "neutral": "普段どおりの自然な話し方で",
}


def _clamp01(v: object) -> float:
    """NaN/inf/None/文字列を0.0に倒し0.0-1.0にclampする。全intensity解決の正典。"""
    try:
        f = float(v or 0.0)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0
    if math.isnan(f) or math.isinf(f):
        return 0.0
    return max(0.0, min(1.0, f))


def build_caption_emotion_directive(emotion: str, intensity: float) -> str:
    """caption LLM 用の感情トーン指示文を組み立てる。感情が空なら空文字（混入防止）。"""
    emo = (emotion or "").strip()
    if not emo:
        return ""
    inten = _clamp01(intensity)
    tone = EMOTION_TONE_HINTS.get(emo, f"「{emo}」の感情に合った話し方で")
    if inten < 0.3:
        tone = "感情を抑えめに、穏やかな話し方で"
    return f"現在の感情は {emo}（強度 {inten:.0%}）です。{tone}、セリフのキャプションを生成してください。"


def build_style_anchor(
    emotion: str,
    intensity: float,
    appearance: str | None = None,
    relationship: str | None = None,
) -> str:
    """決定的スタイルアンカー1文。OFF送信・ON固定条件の共通土台。"""
    emo = (emotion or "").strip()
    inten = _clamp01(intensity)
    if emo and emo in EMOTION_TONE_HINTS:
        tone = EMOTION_TONE_HINTS[emo]
    elif emo:
        # 未知・内面系感情はラベルを潰さない (違和感/戸惑い等を残す)
        tone = f"「{emo}」の内面をにじませた話し方で"
    else:
        tone = "普段どおりの自然な話し方で"
    if emo and inten < 0.3:
        tone = "感情を抑えめに、穏やかな話し方で"
    prefix_parts: list[str] = []
    if relationship:
        prefix_parts.append(f"{relationship}に対して")
    if appearance:
        prefix_parts.append(f"{appearance}雰囲気で")
    prefix = "".join(prefix_parts)
    return f"{prefix}{tone}、全体を通して一貫した声質・感情で話す。"


_LAST_CAPTION: dict[str, tuple[str, float, str]] = {}


def _emotion_bucket(intensity: float) -> float:
    return round(_clamp01(intensity) + 1e-9, 1)


def _tts_cache_key(
    *,
    text: str,
    emotion: str,
    caption: str | None,
    voice_speed: float,
    voice_override: str | None,
) -> str:
    """TTS 音声キャッシュのキー。声（voice_override）も含める — 声違いで旧音声を返さないため。"""
    material = f"{text}|{emotion}|{caption or ''}|{voice_speed}|{voice_override or ''}"
    return hashlib.sha256(material.encode()).hexdigest()


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
        # 感情の声への反映モード: "off" | "anchor" | "llm" (旧2ブール値から移行済み)
        emotion_mode = getattr(chat_config, "voice_emotion_mode", "") or ""
        if not emotion_mode:
            # 正典はSessionConfig._derive_emotion_mode（link OFF + llm ON → "off"）。
            # tts.py側の再導出は後方互換のみで、条件順もSessionConfigに合わせる。
            link = getattr(chat_config, "voice_emotion_link", True)
            llm = getattr(chat_config, "irodori_caption_llm_enabled", False)
            if llm and link:
                emotion_mode = "llm"
            elif link:
                emotion_mode = "anchor"
            else:
                emotion_mode = "off"
        if emotion_mode != "off":
            state_result = ctx.persona_service.get_context(persona)
            if state_result.is_ok and state_result.value:
                state = state_result.value
                emotion = (getattr(state, "emotion", "") or "").strip() or "neutral"

                # 決定的スタイルアンカー1文 (OFF送信・ON固定条件の共通土台。旧メタデータダンプは廃止)
                caption = build_style_anchor(
                    emotion,
                    float(state.emotion_intensity or 0.0),
                    appearance=getattr(state, "appearance", None),
                    relationship=getattr(state, "relationship_status", None),
                )

        # LLM caption generation ("llm" モードのみ。アンカーを磨く)
        if emotion_mode == "llm" and state:
            try:
                # Get LLM config from chat config
                provider_name = getattr(chat_config, "provider", "opencode_go")
                api_key = getattr(chat_config, "api_key", "")
                model_name = getattr(chat_config, "irodori_caption_llm_model", "") or getattr(chat_config, "model", "")
                base_url = getattr(chat_config, "base_url", "")

                from nous.infrastructure.llm.factory import get_provider

                anchor = caption  # OFFアンカーを固定条件・フォールバックに流用
                bucket = _emotion_bucket(float(getattr(state, "emotion_intensity", 0.0) or 0.0))
                cached = _LAST_CAPTION.get(persona)
                if cached and cached[0] == (state.emotion or "") and cached[1] == bucket and cached[2]:
                    caption = cached[2]
                    logger.debug("TTS caption reuse: %s", caption[:60])
                    provider = None
                else:
                    provider = get_provider(provider_name, api_key, model_name, base_url)

                if provider is not None:
                    prev = cached[2] if cached else ""
                    llm_system = """あなたは音声合成（irodori-tts）向けキャプション生成AIです。
【固定条件】の感情・アンカーが主です。本文からの感情推測・感情の切替は禁止します。本文は緩急・間・息遣いの参考にのみ使ってください。
前回 caption の声質を維持し、感情が大きく変わった場合のみ寄せてください。

## 含めるべき要素（該当するもののみ）
- 声の高さ・速さ・質感（落ち着いた/高い/ハスキー/ささやく 等）
- 固定条件の感情の種類と強度（嬉しそう/怒り/悲しみ/驚き/違和感 等）
- 話し方のスタイル（丁寧/カジュアル/近い距離感/遠い距離感）
- 発話の特徴（震え/息遣い/間/たどたどしさ 等）

## 例
- 「落ち着いた声で、近い距離感でやわらかく自然に読み上げてください。全体を通して一貫した声質・感情で話す。」
- 「深く傷つき、今にも泣き出しそうな様子。声が震えており、悲痛なトーンで弱々しく話す。全体を通して一貫した声質・感情で話す。」

## 制約
- 80文字以内の自然な日本語1文
- 必ず「全体を通して一貫した声質・感情で話す。」で締める
- 説明文ではなく「〜話す」「〜読み上げる」で締める
- 出力はキャプションの本文のみ（JSONや説明は不要）"""

                    emotion_directive = build_caption_emotion_directive(
                        str(getattr(state, "emotion", "") or ""),
                        float(getattr(state, "emotion_intensity", 0.0) or 0.0),
                    )
                    if emotion_directive:
                        llm_system = llm_system + "\n" + emotion_directive

                    clamped_inten = _clamp01(getattr(state, "emotion_intensity", 0.0))
                    llm_user = f"""【固定条件】
{anchor}
感情: {emotion} (強度: {clamped_inten:.0%})

【前回】
{prev or "（なし）"}

                    【参考本文(感情決定に使わない)】
{text}"""

                    from nous.infrastructure.llm.base import ErrorEvent, LLMMessage, TextDeltaEvent

                    full_content: list[str] = []
                    saw_error = False
                    async for event in provider.stream(
                        messages=[LLMMessage(role="user", content=llm_user)],
                        system=llm_system,
                        temperature=0.2,
                        max_tokens=128,
                    ):
                        if isinstance(event, TextDeltaEvent):
                            full_content.append(event.content)
                        elif isinstance(event, ErrorEvent):
                            saw_error = True
                            logger.warning("LLM caption generation error: %s", event.message)
                            break
                    llm_caption = "".join(full_content).strip()
                    if llm_caption and not saw_error:
                        caption = llm_caption
                        _LAST_CAPTION[persona] = (state.emotion or "", bucket, caption)
                        logger.info("LLM caption generated for TTS: %s", llm_caption[:100])
                    else:
                        caption = anchor
            except Exception:
                # caption は既に OFFアンカーなので触らない (フォールバック済み)
                logger.exception("LLM caption generation failed, falling back to style anchor")

        # ---- TTS audio cache ----
        voice_speed = getattr(chat_config, "voice_speed", 1.0)
        from nous.config.settings import get_settings

        settings = get_settings()
        cache_dir = Path(settings.data_root) / "persona" / persona / "tts_cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_key = _tts_cache_key(
            text=text,
            emotion=emotion,
            caption=caption,
            voice_speed=voice_speed,
            voice_override=voice_override,
        )
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

    # d4: GET /api/tts/{persona}/voices 削除（内部使用ゼロ。docs言及のみ）
    # d4残り1EP候補（health/cache）はchat-tts.js:198・audio_url・chat-history.jsで使用中のため残す。

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
        if not _PERSONA_PATTERN.match(persona):
            return JSONResponse({"error": "File not found"}, status_code=404)
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
        if not _PERSONA_PATTERN.match(persona):
            return JSONResponse({"ok": False, "error": "File not found"}, status_code=404)
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
