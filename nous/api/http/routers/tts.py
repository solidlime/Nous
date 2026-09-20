from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import math
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple

from starlette.responses import FileResponse, JSONResponse, Response, StreamingResponse

from nous.api.http.deps import _PERSONA_PATTERN, _resolve_persona_from_request, _safe_get_context
from nous.infrastructure.voice.factory import get_voice_engine

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from starlette.requests import Request

    from nous.config.settings import IrodoriConfig

logger = logging.getLogger(__name__)


EMOTION_TONE_HINTS: dict[str, str] = {
    "joy": "明るく弾んだ、声のトーンが上がった話し方",
    "sadness": "落ち着いた、やや低くゆっくりした話し方",
    "anger": "強く短く、勢いのある話し方",
    "surprise": "間と抑揚を大きく、驚きを含んだ話し方",
    "fear": "小さく震える、不安を含んだ話し方",
    "neutral": "普段どおりの自然な話し方",
}


def _intensity_word(intensity: float) -> str:
    """強度0-1を叙述語に。割合表示は学習caption分布外のため使わない。"""
    v = _clamp01(intensity)
    if v < 0.3:
        return "ほのか"
    if v < 0.7:
        return "はっきり"
    return "とても強い"


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
    """caption LLM 用の感情トーン指示文を組み立てる。感情が空なら空文字（混入防止）。叙述文のみ。"""
    emo = (emotion or "").strip()
    if not emo:
        return ""
    inten = _clamp01(intensity)
    tone = EMOTION_TONE_HINTS.get(emo, f"「{emo}」の感情に合った話し方")
    if inten < 0.3:
        tone = "感情を抑えめに、穏やかな話し方"
    return f"いまの感情は{emo}で、強さは{_intensity_word(inten)}。{tone}。"


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
        tone = f"「{emo}」の内面をにじませた話し方"
    else:
        tone = "普段どおりの自然な話し方"
    if emo and inten < 0.3:
        tone = "感情を抑えめに、穏やかな話し方"
    prefix_parts: list[str] = []
    if relationship:
        prefix_parts.append(f"{relationship}に対して")
    if appearance:
        prefix_parts.append(f"{appearance}雰囲気で")
    prefix = "".join(prefix_parts)
    return f"{prefix}{tone}。全体を通して一貫した声質・感情で話す。"


_LAST_CAPTION: dict[str, tuple[str, float, str]] = {}

_CAPTION_TASKS: dict[str, asyncio.Task] = {}


def kickoff_caption_task(persona: str, ctx, user_message: str) -> None:
    """chat開始時に字幕LLMを先行開始する。llmモード以外は何もしない。旧タスクは取消。"""
    prev = _CAPTION_TASKS.pop(persona, None)
    if prev is not None and not prev.done():
        prev.cancel()
    try:
        chat_config = _load_chat_config(persona)
        if _resolve_emotion_mode(chat_config) != "llm":
            return

        async def _run():
            return await _resolve_caption(persona, ctx, chat_config, ref_text=user_message)

        _CAPTION_TASKS[persona] = asyncio.get_running_loop().create_task(_run())
    except Exception:
        logger.exception("caption kickoff failed")


def take_caption_task(persona: str):
    """stream EPが回収する。popなので二重消費なし。"""
    return _CAPTION_TASKS.pop(persona, None)


class CaptionSnapshot(NamedTuple):
    emotion: str
    bucket: float


class CaptionResult(NamedTuple):
    emotion: str
    caption: str | None
    snapshot: CaptionSnapshot


def _emotion_bucket(intensity: float) -> float:
    return round(_clamp01(intensity) + 1e-9, 1)


def _body_str(body: object, key: str) -> str:
    """POST body値の安全なstr取得。欠落/None→""、数値はstr化、bool/list/dict等→""（.strip() crash防止）。"""
    if not isinstance(body, dict):
        return ""
    v = body.get(key)
    if v is None:
        return ""
    if isinstance(v, str):
        return v.strip()
    if isinstance(v, bool):
        return ""
    if isinstance(v, (int, float)):
        return str(v)
    return ""


def _resolve_emotion_mode(chat_config) -> str:
    """感情反映モード解決。正本は SessionConfig._derive_emotion_mode（nous/domain/session_config.py）。
    ここはその条件順をオブジェクト属性向けにミラーしたもの。字幕解決・kickoff共用。"""
    mode = getattr(chat_config, "voice_emotion_mode", "") or ""
    if mode:
        return mode
    link = getattr(chat_config, "voice_emotion_link", True)
    llm = getattr(chat_config, "irodori_caption_llm_enabled", False)
    if llm and link:
        return "llm"
    if link:
        return "anchor"
    return "off"


def _resolve_tts_override(body: object) -> tuple[str, str | None, bool]:
    """emotion/caption override解決。(emotion, caption, use_override)。emotion単独でもoverride扱いしstate再解決を抑止する。"""
    emo = _body_str(body, "emotion")
    cap = _body_str(body, "caption")
    return (emo or "neutral", cap or None, bool(cap or emo))


async def _resolve_caption(
    persona: str,
    ctx,
    chat_config,
    *,
    ref_text: str,
    override_emotion: str = "",
    override_caption: str | None = None,
) -> CaptionResult:
    """感情解決＋字幕決定の正典。synthesize直列・kickoff並列の共用。"""
    use_override = bool(override_emotion or override_caption)
    if use_override:
        emo = (override_emotion or "neutral").strip() or "neutral"
        return CaptionResult(emo, override_caption, CaptionSnapshot(emo, _emotion_bucket(0.0)))
    emotion = "neutral"
    caption: str | None = None
    mode = _resolve_emotion_mode(chat_config)
    state = None
    if mode != "off":
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
    snapshot = CaptionSnapshot(
        emotion,
        _emotion_bucket(float(getattr(state, "emotion_intensity", 0.0) or 0.0)) if state else _emotion_bucket(0.0),
    )
    # LLM caption generation ("llm" モードのみ。アンカーを磨く)
    if mode == "llm" and state:
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
- 「落ち着いた声で、近い距離感でやわらかく自然に読み上げる。全体を通して一貫した声質・感情で話す。」
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
感情: {emotion}（強さ: {_intensity_word(clamped_inten)}）。

【前回】
{prev or "（なし）"}

                    【参考本文(感情決定に使わない)】
{ref_text}"""

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
    return CaptionResult(emotion, caption, snapshot)


def _body_text_required(body: object, key: str) -> str:
    """本文系の厳密取得。strのみ受け付け、前後空白除去。非str/空は""（呼び出し側で400）。"""
    if not isinstance(body, dict):
        return ""
    v = body.get(key)
    if not isinstance(v, str):
        return ""
    return v.strip()


def _find_cache_file(cache_dir: Path, cache_key: str) -> tuple[Path | None, str]:
    """フルハッシュ一致のキャッシュ探索。旧12文字globはstem完全一致のみ救済。戻り値(path|None, url用filename)。"""
    new_path = cache_dir / f"{cache_key}.wav"
    if new_path.exists():
        return new_path, new_path.name
    for p in sorted(cache_dir.glob(f"{cache_key[:12]}*.wav")):
        if p.stem == cache_key:
            logger.warning("TTS legacy cache hit (migrating): %s", p.name)
            return p, p.name
    return None, new_path.name


def _tts_cache_key(
    *,
    text: str,
    emotion: str,
    caption: str | None,
    voice_speed: float,
    voice_override: str | None,
    voice_resolved: str = "",
    model: str = "irodori-tts",
    seed: int | None = 0,
    num_steps: int = 30,
    cfg_text: float = 3.2,
    cfg_speaker: float = 5.0,
    cfg_caption: float = 4.2,
    chunk_min_chars: int = 85,
) -> str:
    """TTS音声キャッシュのキー。解決済みvoice・model・advanced全値を含める。区切り衝突回避のためjson結合。"""
    # "v2": ペイロード配置修正（extra_body→top-level irodori）以前の旧エントリは
    # 指定無視の既定音で作られているため、接頭辞で衝突させず孤児化する（削除はしない）。
    material = json.dumps(
        [
            "v2",
            text,
            emotion,
            caption or "",
            voice_speed,
            voice_override or "",
            voice_resolved,
            model,
            seed or 0,
            num_steps,
            cfg_text,
            cfg_speaker,
            cfg_caption,
            chunk_min_chars,
        ],
        ensure_ascii=False,
        separators=(",", ":"),
    )
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
        # v4.0 (audit L5): fallback は chat 層の既定と同じ 85（単一の正）。bare な
        # 40 は「engine 層の既定が 40」だった頃の名残で、実際の chat TTS 経路は
        # 常に persona 設定値（既定 85）を使うため値が食い違っていた。
        chunk_min_chars=getattr(chat_config, "irodori_chunk_min_chars", 85),
        first_sentence_chunk_min_chars=getattr(chat_config, "irodori_first_sentence_chunk_min_chars", 1),
        seed=getattr(chat_config, "irodori_seed", None),
    )
    return IrodoriConfig(
        url=chat_config.voice_url or global_config.url,
        voice=chat_config.voice_model or global_config.voice,
        model=global_config.model,
        timeout_seconds=global_config.timeout_seconds,
        advanced=advanced,
    )


def _concat_wav(files: list[Path]) -> tuple[bytes, dict]:
    """標準waveでparams検証後にフレーム連結する。params不一致はValueError。"""
    import io
    import wave

    if not files:
        raise ValueError("no files")
    if len(files) > 50:
        raise ValueError("too many files")
    base_params = None
    chunks: list[bytes] = []
    for p in files:
        with wave.open(str(p), "rb") as w:
            params = (w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getcomptype(), w.getcompname())
            frames = w.readframes(w.getnframes())
        if base_params is None:
            base_params = params
        elif params != base_params:
            raise ValueError(f"wav params mismatch: {p.name}")
        chunks.append(frames)
    nchannels, sampwidth, framerate, comptype, compname = base_params  # type: ignore[misc]
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(nchannels)
        w.setsampwidth(sampwidth)
        w.setframerate(framerate)
        w.setcomptype(comptype, compname)
        for c in chunks:
            w.writeframes(c)
    return buf.getvalue(), {"nchannels": nchannels, "sampwidth": sampwidth, "framerate": framerate}


async def _relay_tts_stream(engine, *, text, emotion, caption, speed_arg, cache_path, audio_url) -> AsyncIterator[str]:
    """irodori SSEを中継しつつ蓄積→完了時に結合・保存。途中失敗はcache書込なし・doneなし。"""
    import tempfile

    chunks: list[bytes] = []
    seq = 0
    try:
        async for wav in engine.stream_speech(text=text, emotion=emotion, caption=caption, speed=speed_arg):
            chunks.append(wav)
            yield f"data: {json.dumps({'type': 'tts_chunk', 'seq': seq, 'audio_base64': base64.b64encode(wav).decode('ascii')}, separators=(',', ':'))}\n\n"
            seq += 1
    except Exception:
        logger.exception("TTS stream relay failed")
        yield f"data: {json.dumps({'type': 'tts_error', 'message': 'stream interrupted'}, separators=(',', ':'))}\n\n"
        return
    if not chunks:
        yield f"data: {json.dumps({'type': 'tts_error', 'message': 'no audio chunks'}, separators=(',', ':'))}\n\n"
        return
    try:
        with tempfile.TemporaryDirectory() as tmp:
            paths = []
            for i, blob in enumerate(chunks):
                p = Path(tmp) / f"chunk{i:03d}.wav"
                p.write_bytes(blob)
                paths.append(p)
            combined, _params = _concat_wav(paths)
    except ValueError:
        logger.exception("TTS stream combine failed")
        yield f"data: {json.dumps({'type': 'tts_error', 'message': 'combine failed'}, separators=(',', ':'))}\n\n"
        return
    cache_path.write_bytes(combined)
    yield f"data: {json.dumps({'type': 'tts_done', 'audio_url': audio_url}, separators=(',', ':'))}\n\n"


# ── request handling layer (_do_*) ──────────────────────────────────


def _load_chat_config(persona: str):
    """personaのchat設定を読み込む。TTS各EP共用。"""
    from nous.config.settings import get_settings
    from nous.domain.chat_config import ChatConfigFileRepository

    return ChatConfigFileRepository(get_settings().data_root).get(persona)


async def _parse_json_body(request) -> dict:
    """POST bodyのJSON解析。壊れている/非dictは空dictに倒す。"""
    try:
        body = await request.json()
    except (json.JSONDecodeError, TypeError):
        body = {}
    return body if isinstance(body, dict) else {}


async def _ensure_voice_engine_ready(engine) -> str | None:
    """TTSエンジンの起動確認。正常なら None、問題ならエラーメッセージ。"""
    try:
        if await engine.health_check():
            return None
        return "Voice engine health check failed"
    except Exception:
        # TTSエンジン未起動は期待された503経路。スタックは不要。
        logger.warning("voice engine unreachable during TTS request")
        return "Voice engine unreachable"


def _apply_voice_override(engine, voice_override: str | None) -> None:
    """voice上書き (body > chat_config.voice_model)。リクエスト単位でengineへ反映。"""
    if not voice_override:
        return
    from nous.infrastructure.voice.irodori import IrodoriEngine

    if isinstance(engine, IrodoriEngine):
        engine.set_voice(voice_override)


def _tts_voice_speed(chat_config) -> float:
    """voice_speed の取得。0/欠落は1.0扱い。"""
    return float(getattr(chat_config, "voice_speed", 1.0) or 1.0)


def _tts_cache_dir(persona: str) -> Path:
    """personaのTTSキャッシュディレクトリ（無ければ作成）。"""
    from nous.config.settings import get_settings

    cache_dir = Path(get_settings().data_root) / "persona" / persona / "tts_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def _tts_cache_key_for(
    *,
    text: str,
    emotion: str,
    caption: str | None,
    voice_speed: float,
    voice_override: str | None,
    voice_resolved: str,
    irodori_config: IrodoriConfig,
) -> str:
    """irodori_config 込みのキャッシュキー。synthesize/stream共用。"""
    adv = irodori_config.advanced
    return _tts_cache_key(
        text=text,
        emotion=emotion,
        caption=caption,
        voice_speed=voice_speed,
        voice_override=voice_override,
        voice_resolved=voice_resolved,
        model=irodori_config.model,
        seed=adv.seed,
        num_steps=adv.num_steps,
        cfg_text=adv.cfg_scale_text,
        cfg_speaker=adv.cfg_scale_speaker,
        cfg_caption=adv.cfg_scale_caption,
        chunk_min_chars=adv.chunk_min_chars,
    )


def _tts_audio_payload(audio_bytes: bytes, audio_url: str, emotion: str, caption: str | None) -> dict:
    """キャッシュHIT/MISS共通の200レスポンス。"""
    return {
        "ok": True,
        "audio_base64": base64.b64encode(audio_bytes).decode("ascii"),
        "audio_url": audio_url,
        "format": "wav",
        "emotion": emotion,
        "caption": caption,
    }


async def _do_synthesize_tts(persona: str, ctx, body: dict) -> tuple[dict, int]:
    """POST /api/tts/{persona} の本体。戻り値は (payload, status_code)。"""
    chat_config = _load_chat_config(persona)
    irodori_config = _get_irodori_config(ctx, chat_config)
    engine = get_voice_engine(irodori_config)

    engine_error = await _ensure_voice_engine_ready(engine)
    if engine_error:
        return {"ok": False, "error": engine_error}, 503

    text = _body_text_required(body, "text")
    if not text:
        return {"ok": False, "error": "text is required"}, 400

    # Optional voice override (body > chat_config.voice_model > global)
    voice_override = _body_str(body, "voice") or (chat_config.voice_model or None)
    _apply_voice_override(engine, voice_override)

    # get persona state for emotion + build caption
    ov_emo, ov_cap, use_override = _resolve_tts_override(body)
    override_emotion, override_caption = (ov_emo if use_override else "", ov_cap if use_override else None)
    caption_res = await _resolve_caption(
        persona,
        ctx,
        chat_config,
        ref_text=text,
        override_emotion=override_emotion,
        override_caption=override_caption,
    )
    emotion, caption = caption_res.emotion, caption_res.caption

    # ---- TTS audio cache ----
    voice_speed = _tts_voice_speed(chat_config)
    # 1.0近傍は感情速度に委譲（厳密な==ではなく許容誤差で判定）
    speed_arg = None if abs(voice_speed - 1.0) < 1e-9 else voice_speed
    voice_resolved = voice_override or chat_config.voice_model or ctx.settings.irodori.voice
    cache_key = _tts_cache_key_for(
        text=text,
        emotion=emotion,
        caption=caption,
        voice_speed=voice_speed,
        voice_override=voice_override,
        voice_resolved=voice_resolved,
        irodori_config=irodori_config,
    )
    cache_dir = _tts_cache_dir(persona)
    new_cache_path = cache_dir / f"{cache_key}.wav"
    found_path, audio_url_filename = _find_cache_file(cache_dir, cache_key)
    audio_url = f"/api/tts/{persona}/cache/{audio_url_filename}"

    if found_path:
        logger.debug("TTS cache HIT: %s", found_path)
        return _tts_audio_payload(found_path.read_bytes(), audio_url, emotion, caption), 200

    try:
        audio_bytes = await engine.synthesize(
            text=text,
            emotion=emotion,
            caption=caption,
            speed=speed_arg,
        )
    except Exception:
        logger.warning("TTS synthesis failed for persona '%s'", persona, exc_info=True)
        return {"ok": False, "error": "Voice synthesis failed"}, 500
    new_cache_path.write_bytes(audio_bytes)
    logger.debug("TTS cache MISS: %s", new_cache_path)
    return _tts_audio_payload(audio_bytes, audio_url, emotion, caption), 200


async def _do_resolve_stream_caption(persona: str, ctx, chat_config, body: dict, *, ref_text: str):
    """stream EPの字幕解決。body override → 並列タスク回収（不一致/失敗時は直列後退）。"""
    ov_emo, ov_cap, use_override = _resolve_tts_override(body)
    override_emotion, override_caption = (ov_emo if use_override else "", ov_cap if use_override else None)
    caption_res = await _resolve_caption(
        persona,
        ctx,
        chat_config,
        ref_text=ref_text,
        override_emotion=override_emotion,
        override_caption=override_caption,
    )
    task = take_caption_task(persona)
    if task is not None and _resolve_emotion_mode(chat_config) == "llm":
        try:
            parallel = await asyncio.wait_for(task, timeout=20.0)
            st = ctx.persona_service.get_context(persona)
            if st.is_ok and st.value:
                now_emo = (getattr(st.value, "emotion", "") or "").strip() or "neutral"
                now_bucket = _emotion_bucket(float(getattr(st.value, "emotion_intensity", 0.0) or 0.0))
                if now_emo == parallel.snapshot.emotion and now_bucket == parallel.snapshot.bucket:
                    caption_res = parallel
                    logger.debug("TTS caption parallel hit")
        except Exception:
            logger.exception("caption parallel consume failed")
    return caption_res


async def _do_stream_tts(persona: str, ctx, body: dict) -> Response:
    """POST /api/tts/{persona}/stream の本体。SSE応答を返す（起動エラーはJSON）。"""
    chat_config = _load_chat_config(persona)
    irodori_config = _get_irodori_config(ctx, chat_config)
    engine = get_voice_engine(irodori_config)

    engine_error = await _ensure_voice_engine_ready(engine)
    if engine_error:
        return JSONResponse({"ok": False, "error": engine_error}, status_code=503)

    text = _body_text_required(body, "text")
    if not text:
        return JSONResponse({"ok": False, "error": "text is required"}, status_code=400)

    # Optional voice override (body > chat_config.voice_model > global)
    voice_override = _body_str(body, "voice") or (chat_config.voice_model or None)
    _apply_voice_override(engine, voice_override)

    voice_speed = _tts_voice_speed(chat_config)
    speed_arg = None if abs(voice_speed - 1.0) < 1e-9 else voice_speed
    voice_resolved = voice_override or chat_config.voice_model or ctx.settings.irodori.voice

    caption_res = await _do_resolve_stream_caption(persona, ctx, chat_config, body, ref_text=text)
    emotion, caption = caption_res.emotion, caption_res.caption

    # ---- TTS audio cache ----
    cache_dir = _tts_cache_dir(persona)
    cache_key = _tts_cache_key_for(
        text=text,
        emotion=emotion,
        caption=caption,
        voice_speed=voice_speed,
        voice_override=voice_override,
        voice_resolved=voice_resolved,
        irodori_config=irodori_config,
    )
    new_cache_path = cache_dir / f"{cache_key}.wav"
    found_path, audio_url_filename = _find_cache_file(cache_dir, cache_key)
    audio_url = f"/api/tts/{persona}/cache/{audio_url_filename}"

    if found_path:
        blob = found_path.read_bytes()

        async def _hit_stream():
            chunk = {"type": "tts_chunk", "seq": 0, "audio_base64": base64.b64encode(blob).decode("ascii")}
            yield f"data: {json.dumps(chunk, separators=(',', ':'))}\n\n"
            done = {"type": "tts_done", "audio_url": audio_url}
            yield f"data: {json.dumps(done, separators=(',', ':'))}\n\n"

        return StreamingResponse(_hit_stream(), media_type="text/event-stream; charset=utf-8")

    return StreamingResponse(
        _relay_tts_stream(
            engine,
            text=text,
            emotion=emotion,
            caption=caption,
            speed_arg=speed_arg,
            cache_path=new_cache_path,
            audio_url=audio_url,
        ),
        media_type="text/event-stream; charset=utf-8",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _do_tts_health(persona: str, ctx) -> dict:
    """GET /api/tts/{persona}/health の本体。irodori /v1/models を見て接続状態を返す。"""
    chat_config = _load_chat_config(persona)
    base_url = _get_irodori_config(ctx, chat_config).url.rstrip("/")

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
            return {"ok": True, "connected": True, "url": base_url, "models": models}
    except Exception:
        return {"ok": True, "connected": False, "url": base_url, "error": "Connection check failed"}


def _sanitize_cache_filename(filename: object) -> str | None:
    """cache filenameのサニタイズ（serve/delete共用15行重複の統合）。
    basename化＋".."除去。空・wav以外は None。"""
    import os

    safe_name = os.path.basename(str(filename)).replace("..", "").strip()
    if not safe_name or not safe_name.lower().endswith(".wav"):
        return None
    return safe_name


def _do_serve_tts_cache(persona: str, safe_name: str) -> dict | None:
    """cacheファイルの解決。不在は None（応答組み立ては呼び出し側）。"""
    file_path = _tts_cache_dir(persona) / safe_name
    if not file_path.exists():
        return None
    import mimetypes

    mime_type, _ = mimetypes.guess_type(safe_name)
    return {"file_path": str(file_path), "mime_type": mime_type or "audio/wav"}


def _do_delete_tts_cache(persona: str, safe_name: str) -> bool:
    """cacheファイルの削除。冪等 — 不在は False。"""
    file_path = _tts_cache_dir(persona) / safe_name
    if not file_path.exists():
        return False
    file_path.unlink()
    return True


def register_tts_routes(mcp) -> None:
    @mcp.custom_route("/api/tts/{persona}", methods=["POST"])
    async def synthesize_tts(request: Request) -> JSONResponse:
        """POST /api/tts/{persona} — synthesize TTS audio."""
        persona = _resolve_persona_from_request(request)
        ctx = _safe_get_context(persona)
        if not ctx:
            return JSONResponse({"ok": False, "error": "Persona not found"}, status_code=404)
        payload, status = await _do_synthesize_tts(persona, ctx, await _parse_json_body(request))
        return JSONResponse(payload, status_code=status)

    @mcp.custom_route("/api/tts/{persona}/stream", methods=["POST"])
    async def stream_tts(request: Request) -> Response:
        """POST /api/tts/{persona}/stream — stream TTS audio via SSE."""
        persona = _resolve_persona_from_request(request)
        ctx = _safe_get_context(persona)
        if not ctx:
            return JSONResponse({"ok": False, "error": "Persona not found"}, status_code=404)
        return await _do_stream_tts(persona, ctx, await _parse_json_body(request))

    # d4: GET /api/tts/{persona}/voices 削除（内部使用ゼロ。docs言及のみ）
    # d4残り1EP候補（health/cache）はchat-tts.js:198・audio_url・chat-history.jsで使用中のため残す。

    @mcp.custom_route("/api/tts/{persona}/health", methods=["GET"])
    async def health_check_tts(request: Request) -> JSONResponse:
        """GET /api/tts/{persona}/health — check irodori connectivity."""
        persona = _resolve_persona_from_request(request)
        ctx = _safe_get_context(persona)
        if not ctx:
            return JSONResponse({"ok": True, "connected": False, "error": "Persona not found"}, status_code=404)
        return JSONResponse(await _do_tts_health(persona, ctx))

    @mcp.custom_route("/api/tts/{persona}/cache/{filename}", methods=["GET"])
    async def serve_tts_cache(request: Request) -> Response:
        """GET /api/tts/{persona}/cache/{filename} — serve cached TTS audio."""
        persona = _resolve_persona_from_request(request)
        if not _PERSONA_PATTERN.match(persona):
            return JSONResponse({"error": "File not found"}, status_code=404)
        safe_name = _sanitize_cache_filename(request.path_params.get("filename", ""))
        if not safe_name:
            return JSONResponse({"error": "Invalid filename"}, status_code=400)
        result = _do_serve_tts_cache(persona, safe_name)
        if result is None:
            return JSONResponse({"error": "File not found"}, status_code=404)
        return FileResponse(result["file_path"], media_type=result["mime_type"])

    @mcp.custom_route("/api/tts/{persona}/cache/{filename}", methods=["DELETE"])
    async def delete_tts_cache(request: Request) -> JSONResponse:
        """DELETE /api/tts/{persona}/cache/{filename} — delete a cached TTS audio file. Idempotent."""
        persona = _resolve_persona_from_request(request)
        if not _PERSONA_PATTERN.match(persona):
            return JSONResponse({"ok": False, "error": "File not found"}, status_code=404)
        safe_name = _sanitize_cache_filename(request.path_params.get("filename", ""))
        if not safe_name:
            return JSONResponse({"ok": False, "error": "Invalid filename"}, status_code=400)
        return JSONResponse({"ok": True, "deleted": _do_delete_tts_cache(persona, safe_name)})
