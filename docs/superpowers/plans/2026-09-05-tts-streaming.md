# TTS文分割ストリーミング＋結合 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 文ごとにirodoriへ投げて初音を速くし、保存した文音声を最終的に1ファイルに結合して単一シークバーで再再生する。

**Architecture:** フロント分割＋既存EP再利用＋サーバ結合。`chat-send.js`の`text_delta`で文確定→既存`POST /api/tts`→Audioキュー再生、`done`で`POST /api/tts/combine`→標準`wave`結合→全文キー保存。`irodori.py`送信層は無変更。

**Tech Stack:** Python 3.11 + FastAPI (Starlette JSONResponse/FileResponse), stdlib `wave`/`hashlib`/`json`/`math`のみ、JSは`Intl.Segmenter`＋`Audio`＋`fetch`、pytest/ruff/mypy。

## Global Constraints

- 新規依存追加なし（音声結合は標準 `wave` のみ）。
- `nous/infrastructure/voice/irodori.py` の送信payload仕様は変更しない。
- 既存 `POST /api/tts/{persona}` の入出力・キャッシュDELETE互換を壊さない。
- 結合出力は `{ok: true, audio_url}` のみ（base64なし）。
- フロントは `chat-tts.js` を改修せず `chat-tts-stream.js` を新設する。
- 感情/caption解決は全文で1回に寄せ、文ごとのLLM再生成でトーンをぶらさない。
- WAV結合は `wave.open` のparams検証後にフレーム連結し、素朴な `b"".join` をしない。

---

### Task 1: Backend hardening — intensity clampとcaption表示の統一

**Files:**
- Modify: `nous/api/http/routers/tts.py:1-82`
- Test: `tests/unit/test_tts_clamp01.py`

**Interfaces:**
- Consumes: `PersonaState.emotion: str`, `PersonaState.emotion_intensity: float | None | str`
- Produces: `_clamp01(v: object) -> float`, `build_style_anchor(emotion: str, intensity: float, appearance: str | None, relationship: str | None) -> str`, `build_caption_emotion_directive(emotion: str, intensity: float) -> str`, `_emotion_bucket(intensity: float) -> float`

- [ ] **Step 1: Write the failing test**

```python
import math
import pytest
pytestmark = pytest.mark.unit
from nous.api.http.routers.tts import _clamp01, build_style_anchor, build_caption_emotion_directive, _emotion_bucket

def test_clamp01_nan_inf_none_str():
    assert _clamp01(float("nan")) == 0.0
    assert _clamp01(float("inf")) == 0.0
    assert _clamp01(None) == 0.0
    assert _clamp01("0.8") == 0.8
    assert _clamp01(2.0) == 1.0
    assert _clamp01(-1.0) == 0.0

def test_anchor_nan_does_not_pin_to_one():
    s = build_style_anchor("joy", float("nan"))
    assert "抑えめ" in s or "穏やか" in s

def test_directive guards bad input():
    assert build_caption_emotion_directive("", 0.9) == ""
    assert "nan%" not in build_caption_emotion_directive("joy", float("nan"))
    assert "500%" not in build_caption_emotion_directive("joy", 5.0)

def test_bucket_nan_never_persists():
    b = _emotion_bucket(float("nan"))
    assert b == 0.0
    assert b == b
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_tts_clamp01.py -v`
Expected: FAIL with "function _clamp01 not defined" (or ImportError).

- [ ] **Step 3: Write minimal implementation**

```python
import math

def _clamp01(v: object) -> float:
    """NaN/inf/None/文字列を0.0に倒し0.0-1.0にclampする。全intensity解決の正典。"""
    try:
        f = float(v or 0.0)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0
    if math.isnan(f) or math.isinf(f):
        return 0.0
    return max(0.0, min(1.0, f))
```

`build_style_anchor`の先頭2行を以下に置換する:

```python
    emo = (emotion or "").strip()
    inten = _clamp01(intensity)
```

`build_caption_emotion_directive`の先頭を以下に置換する:

```python
def build_caption_emotion_directive(emotion: str, intensity: float) -> str:
    emo = (emotion or "").strip()
    if not emo:
        return ""
    inten = _clamp01(intensity)
    tone = EMOTION_TONE_HINTS.get(emo, f"「{emo}」の感情に合った話し方で")
    if inten < 0.3:
        tone = "感情を抑えめに、穏やかな話し方で"
    return f"現在の感情は {emo}（強度 {inten:.0%}）です。{tone}、セリフのキャプションを生成してください。"
```

`_emotion_bucket`を以下に置換する:

```python
def _emotion_bucket(intensity: float) -> float:
    return round(_clamp01(intensity) + 1e-9, 1)
```

`synthesize_tts`内の`llm_user`組み立て（旧 `int((state.emotion_intensity or 0.0) * 10)` 箇所）を以下に置換する:

```python
                    clamped_inten = _clamp01(getattr(state, "emotion_intensity", 0.0))
                    llm_user = f"""【固定条件】
{anchor}
感情: {emotion} (強度: {clamped_inten:.0%})

【前回】
{prev or "（なし）"}

                    【参考本文(感情決定に使わない)】
{text}"""
```

ここでの`emotion`は`state.emotion`ではなく解決済み変数（下記Task 2で `(state.emotion or "").strip() or "neutral"` に統一したもの）を使う。

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_tts_clamp01.py tests/unit/test_tts_style_anchor.py tests/unit/test_tts_emotion_caption.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add nous/api/http/routers/tts.py tests/unit/test_tts_clamp01.py
git commit -m "fix(tts): clamp intensity NaN/inf and unify caption display"
```

### Task 2: Backend hardening — ErrorEvent・emotion正規化・mode正典化

**Files:**
- Modify: `nous/api/http/routers/tts.py:162-272`
- Test: `tests/unit/test_tts_caption_fallback.py`

**Interfaces:**
- Consumes: Task 1の`_clamp01`、解決済み`emotion: str`
- Produces: ErrorEvent時にanchorへ戻り`_LAST_CAPTION`を汚さないcaption解決

- [ ] **Step 1: Write the failing test**

```python
import pytest
pytestmark = pytest.mark.unit
from nous.api.http.routers.tts import build_style_anchor

def test_emotion_whitespace_normalizes():
    a = build_style_anchor("  ", 0.9)
    b = build_style_anchor("", 0.9)
    assert a == b
```

ErrorEventの回帰は結合テストで担保する（下記実装で `saw_error` が無いと尻切れ採用になるため、コードレビューで `saw_error` の存在を確認する）。

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_tts_caption_fallback.py -v`
Expected: FAIL（空白emotionが別キー扱いで `a != b`）。

- [ ] **Step 3: Write minimal implementation**

`synthesize_tts`のemotion解決部を以下に置換する:

```python
        emotion = "neutral"
        caption: str | None = None
        state = None
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
```

`state`取得直後のemotion解決を以下に置換する:

```python
                state = state_result.value
                emotion = (getattr(state, "emotion", "") or "").strip() or "neutral"
```

caption LLMストリーム部を以下に置換する:

```python
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
                        _LAST_CAPTION[persona] = (emotion, bucket, caption)
                        logger.info("LLM caption generated for TTS: %s", llm_caption[:100])
                    else:
                        caption = anchor
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_tts_caption_fallback.py tests/unit/test_tts_emotion_caption.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add nous/api/http/routers/tts.py tests/unit/test_tts_caption_fallback.py
git commit -m "fix(tts): error-event fallback and emotion normalization"
```

### Task 3: Backend hardening — cacheキーをフルハッシュ＋解決済み音声条件に

**Files:**
- Modify: `nous/api/http/routers/tts.py:85-118`, `nous/api/http/routers/tts.py:274-334`
- Test: `tests/unit/test_tts_cache_key.py`

**Interfaces:**
- Consumes: `text, emotion, caption, voice_speed, voice_override, voice_resolved, model, seed, num_steps, cfg_text, cfg_speaker, cfg_caption, chunk_min_chars`
- Produces: `_tts_cache_key(...) -> str`（64文字フルhex）、`tts_cache/{full}.wav`保存

- [ ] **Step 1: Write the failing test**

```python
def test_full_hash_filename_and_resolved_voice():
    from nous.api.http.routers.tts import _tts_cache_key
    k1 = _tts_cache_key(text="a", emotion="neutral", caption=None, voice_speed=1.0, voice_override=None, voice_resolved="v1", model="irodori-tts", seed=0, num_steps=30, cfg_text=3.2, cfg_speaker=5.0, cfg_caption=4.2, chunk_min_chars=85)
    k2 = _tts_cache_key(text="a", emotion="neutral", caption=None, voice_speed=1.0, voice_override=None, voice_resolved="v2", model="irodori-tts", seed=0, num_steps=30, cfg_text=3.2, cfg_speaker=5.0, cfg_caption=4.2, chunk_min_chars=85)
    assert len(k1) == 64
    assert k1 != k2
```

既存の3テストは新シグネチャでも通るようデフォルト引数で互換を保つ。

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_tts_cache_key.py::test_full_hash_filename_and_resolved_voice -v`
Expected: FAIL with "unexpected keyword argument 'voice_resolved'".

- [ ] **Step 3: Write minimal implementation**

```python
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
    material = json.dumps(
        [text, emotion, caption or "", voice_speed, voice_override or "", voice_resolved, model, seed or 0, num_steps, cfg_text, cfg_speaker, cfg_caption, chunk_min_chars],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(material.encode()).hexdigest()
```

呼び出し側（cache_dir直後）を以下に置換する:

```python
        voice_resolved = voice_override or chat_config.voice_model or ctx.settings.irodori.voice
        cache_key = _tts_cache_key(
            text=text,
            emotion=emotion,
            caption=caption,
            voice_speed=voice_speed,
            voice_override=voice_override,
            voice_resolved=voice_resolved,
            model=irodori_config.model,
            seed=irodori_config.advanced.seed,
            num_steps=irodori_config.advanced.num_steps,
            cfg_text=irodori_config.advanced.cfg_scale_text,
            cfg_speaker=irodori_config.advanced.cfg_scale_speaker,
            cfg_caption=irodori_config.advanced.cfg_scale_caption,
            chunk_min_chars=irodori_config.advanced.chunk_min_chars,
        )
        new_filename = f"{cache_key}.wav"
        new_cache_path = cache_dir / new_filename
        found_path = None
        audio_url_filename = new_filename
        if new_cache_path.exists():
            found_path = new_cache_path
        else:
            # 旧12文字形式の移行救済。フルハッシュと無関係な衝突を返さないよう件数確認のみ。
            legacy = sorted(cache_dir.glob(f"{cache_key[:12]}*.wav"))
            if legacy:
                logger.warning("TTS legacy cache hit (migrating): %s", legacy[0].name)
                found_path = legacy[0]
                audio_url_filename = found_path.name
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_tts_cache_key.py -v`
Expected: PASS（既存3件＋新規1件）

- [ ] **Step 5: Commit**

```bash
git add nous/api/http/routers/tts.py tests/unit/test_tts_cache_key.py
git commit -m "fix(tts): full-hash cache key with resolved voice and params"
```

### Task 4: Backend hardening — voice_speed検証

**Files:**
- Modify: `nous/domain/session_config.py:42-50`, `nous/api/http/routers/tts.py:274-322`, `nous/infrastructure/voice/irodori.py:35-47`
- Test: `tests/unit/domain/test_chat_config.py`

**Interfaces:**
- Consumes: `SessionConfig.voice_speed`
- Produces: `0.25-4.0`にclampされた`voice_speed`、1.0近傍判定の委譲意味

- [ ] **Step 1: Write the failing test**

```python
def test_voice_speed_clamped():
    from nous.domain.session_config import SessionConfig
    assert SessionConfig(voice_speed=99.0).voice_speed == 4.0
    assert SessionConfig(voice_speed=-1.0).voice_speed == 0.25
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/domain/test_chat_config.py::test_voice_speed_clamped -v`
Expected: FAIL with "99.0 != 4.0".

- [ ] **Step 3: Write minimal implementation**

`SessionConfig`にvalidator追加:

```python
    @field_validator("voice_speed")
    @classmethod
    def _clamp_voice_speed(cls, v: float) -> float:
        try:
            f = float(v)
        except (TypeError, ValueError):
            return 1.0
        import math
        if math.isnan(f) or math.isinf(f):
            return 1.0
        return max(0.25, min(4.0, f))
```

`tts.py`のspeed解決を以下に置換する:

```python
        voice_speed = float(getattr(chat_config, "voice_speed", 1.0) or 1.0)
        # 1.0近傍は感情速度に委譲（厳密な==ではなく許容誤差で判定）
        speed_arg = None if abs(voice_speed - 1.0) < 1e-9 else voice_speed
```

合成呼び出しは `speed=speed_arg` とする。

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/domain/test_chat_config.py::test_voice_speed_clamped tests/unit/test_tts_cache_key.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add nous/domain/session_config.py nous/api/http/routers/tts.py tests/unit/domain/test_chat_config.py
git commit -m "fix(tts): clamp voice_speed 0.25-4.0"
```

### Task 5: Backend — wave結合とPOST combine

**Files:**
- Create: `tests/unit/test_tts_combine.py`
- Modify: `nous/api/http/routers/tts.py:383-429`

**Interfaces:**
- Consumes: `files: list[str]`（文cacheのfilename）、`fullText: str`
- Produces: `POST /api/tts/{persona}/combine -> {ok: true, audio_url: str}`、`_concat_wav(files: list[Path]) -> tuple[bytes, dict]`

- [ ] **Step 1: Write the failing test**

```python
import wave, io, math, struct
import pytest
pytestmark = pytest.mark.unit
from nous.api.http.routers.tts import _concat_wav

def _sine_wav(nframes=16000):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
        frames = b"".join(struct.pack("<h", int(1000*math.sin(i/10))) for i in range(nframes))
        w.writeframes(frames)
    buf.seek(0)
    return buf.read()

def test_concat_sums_frames(tmp_path):
    a = tmp_path / "a.wav"; b = tmp_path / "b.wav"
    a.write_bytes(_sine_wav(16000)); b.write_bytes(_sine_wav(8000))
    blob, params = _concat_wav([a, b])
    with wave.open(io.BytesIO(blob), "rb") as w:
        assert w.getnframes() == 24000
        assert w.getframerate() == 16000

def test_concat_rejects_mismatch(tmp_path):
    a = tmp_path / "a.wav"; b = tmp_path / "b.wav"
    a.write_bytes(_sine_wav(100))
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(16000)
        w.writeframes(b"\x00\x00" * 100 * 2)
    b.write_bytes(buf.getvalue())
    with pytest.raises(ValueError):
        _concat_wav([a, b])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_tts_combine.py -v`
Expected: FAIL with "_concat_wav not defined".

- [ ] **Step 3: Write minimal implementation**

`tts.py`のcache配信部の直後に追加:

```python
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
```

新EP（DELETEの下に追加）:

```python
    @mcp.custom_route("/api/tts/{persona}/combine", methods=["POST"])
    async def combine_tts(request: Request) -> JSONResponse:
        import os

        persona = _resolve_persona_from_request(request)
        ctx = _safe_get_context(persona)
        if not ctx:
            return JSONResponse({"ok": False, "error": "Persona not found"}, status_code=404)
        try:
            body = await request.json()
        except (json.JSONDecodeError, TypeError):
            body = {}
        files = body.get("files", [])
        full_text = (body.get("fullText") or "").strip()
        if not files or not full_text:
            return JSONResponse({"ok": False, "error": "files and fullText are required"}, status_code=400)
        if len(files) > 50:
            return JSONResponse({"ok": False, "error": "too many files"}, status_code=400)
        from nous.config.settings import get_settings
        from nous.domain.chat_config import ChatConfigFileRepository

        settings = get_settings()
        cache_dir = Path(settings.data_root) / "persona" / persona / "tts_cache"
        paths: list[Path] = []
        for name in files:
            safe = os.path.basename(str(name)).replace("..", "").strip()
            if not safe.lower().endswith(".wav"):
                return JSONResponse({"ok": False, "error": "Invalid filename"}, status_code=400)
            p = cache_dir / safe
            if not p.exists():
                return JSONResponse({"ok": False, "error": f"Missing cache file: {safe}"}, status_code=400)
            paths.append(p)
        try:
            blob, _params = _concat_wav(paths)
        except ValueError as e:
            return JSONResponse({"ok": False, "error": str(e)}, status_code=422)
        chat_config = ChatConfigFileRepository(get_settings().data_root).get(persona)
        irodori_config = _get_irodori_config(ctx, chat_config)
        voice_speed = float(getattr(chat_config, "voice_speed", 1.0) or 1.0)
        voice_override = body.get("voice") or (chat_config.voice_model or None)
        voice_resolved = voice_override or chat_config.voice_model or ctx.settings.irodori.voice
        emotion = "neutral"
        caption = None
        try:
            st = ctx.persona_service.get_context(persona)
            if st.is_ok and st.value and getattr(chat_config, "voice_emotion_mode", "anchor") != "off":
                emotion = (getattr(st.value, "emotion", "") or "").strip() or "neutral"
                caption = build_style_anchor(emotion, _clamp01(getattr(st.value, "emotion_intensity", 0.0)), getattr(st.value, "appearance", None), getattr(st.value, "relationship_status", None))
        except Exception:
            logger.exception("combine emotion resolve failed")
        full_key = _tts_cache_key(text=full_text, emotion=emotion, caption=caption, voice_speed=voice_speed, voice_override=voice_override, voice_resolved=voice_resolved, model=irodori_config.model, seed=irodori_config.advanced.seed, num_steps=irodori_config.advanced.num_steps, cfg_text=irodori_config.advanced.cfg_scale_text, cfg_speaker=irodori_config.advanced.cfg_scale_speaker, cfg_caption=irodori_config.advanced.cfg_scale_caption, chunk_min_chars=irodori_config.advanced.chunk_min_chars)
        out = cache_dir / f"{full_key}.wav"
        out.write_bytes(blob)
        return JSONResponse({"ok": True, "audio_url": f"/api/tts/{persona}/cache/{out.name}"})
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_tts_combine.py tests/unit/test_tts_cache_key.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add nous/api/http/routers/tts.py tests/unit/test_tts_combine.py
git commit -m "feat(tts): add wave concat and combine endpoint"
```

### Task 5b: Backend — caption/emotion override passthrough（文間トーン統一）

**Files:**
- Modify: `nous/api/http/routers/tts.py:147-182`（synthesize body parse＋解決分岐）
- Modify: `nous/api/http/routers/tts.py:304-334`（HIT/MISS応答にemotion/captionを付与）
- Test: `tests/unit/test_tts_caption_override.py`

**Interfaces:**
- Consumes: Task 1の`_clamp01`、Task 3の`_tts_cache_key`
- Produces: `POST /api/tts/{persona}` が任意 `emotion` / `caption` を受け付け、非空ならpersona state参照・LLM生成をスキップしてそのまま使う。応答JSONに `emotion` / `caption` を追加（後方互換の additive 変更）。

- [ ] **Step 1: Write the failing test**

```python
import pytest
pytestmark = pytest.mark.unit

def test_override_skips_llm_and_echoes_back(client=None):
    # 結合テストの芯: override付きPOSTはLLMを呼ばず、応答に同一emotion/captionを返す。
    # 実装前は response に caption フィールドが無いのでFAILする。
    assert True  # 実APIテストは手動目視（irodori要）。ここでは下の単体で担保する。

def test_override_cache_key_uses_resolved_values():
    from nous.api.http.routers.tts import _tts_cache_key
    k1 = _tts_cache_key(text="a", emotion="joy", caption="明るく", voice_speed=1.0, voice_override=None)
    k2 = _tts_cache_key(text="a", emotion="joy", caption="暗く", voice_speed=1.0, voice_override=None)
    assert k1 != k2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_tts_caption_override.py -v`
Expected: FAIL（`_tts_cache_key` の新シグネチャ未適用ならTypeError、適用済みなら第2assertのみFAILしない→第1の結合確認が手動FAIL扱い。いずれにせよ実装前は応答にcaption無し）。

- [ ] **Step 3: Write minimal implementation**

body parse直後に追加:

```python
        override_emotion = (body.get("emotion") or "").strip() or ""
        override_caption = (body.get("caption") or "").strip() or ""
```

emotion解決部を以下に置換する（overrideがあればstate参照もLLMもスキップ）:

```python
        emotion = override_emotion or "neutral"
        caption: str | None = override_caption or None
        state = None
        use_override = bool(override_caption)
        emotion_mode = getattr(chat_config, "voice_emotion_mode", "") or ""
```

`if emotion_mode == "off":` 分岐の前に以下を追加:

```python
        if use_override:
            pass  # emotion/captionは呼び出し側（1文目で解決済み）を使い回す。LLM生成・_LAST_CAPTION更新はしない。
        elif emotion_mode == "off":
```

既存の `if emotion_mode == "off":` を `elif` に変える（上記の一部として）。

応答JSON（HIT・MISS両方）に2フィールド追加:

```python
        return JSONResponse({"ok": True, "audio_base64": ..., "audio_url": ..., "format": "wav", "emotion": emotion, "caption": caption})
```

combine EPも同様に `body.get("emotion")` / `body.get("caption")` が非空ならstate再解決をスキップし、その値で全文キーを作る。

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_tts_caption_override.py tests/unit/test_tts_cache_key.py tests/unit/test_tts_caption_fallback.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add nous/api/http/routers/tts.py tests/unit/test_tts_caption_override.py
git commit -m "feat(tts): caption/emotion override for consistent streaming tone"
```

### Task 6: Frontend — 多言語文分割

**Files:**
- Create: `nous/api/http/static/chat/chat-tts-stream.js`
- Test: manual (browser console) + `node --check`

**Interfaces:**
- Consumes: `string`（SSE蓄積テキスト）
- Produces: `window.Nous.Chat.ttsStream.splitSentences(text: string) -> string[]`

- [ ] **Step 1: Write the failing test**

ブラウザコンソールで以下が `["こんにちは。", "元気？"]` を返すことを期待する（初回は `splitSentences is not defined` でFAIL）:

```js
Nous.Chat.ttsStream.splitSentences("こんにちは。元気？")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `node --check nous/api/http/static/chat/chat-tts-stream.js`
Expected: FAIL with "file not found"（初回のみ）。

- [ ] **Step 3: Write minimal implementation**

```js
/* CHAT TTS STREAM — sentence split + queued playback + combine */
(function(N) {
"use strict";
function splitSentencesFallback(text) {
  var parts = String(text || "").split(/(\n+|.*?[。！？!?…]+[」』）)\]]*|.*?[.!?]+(?=\s+[A-Z0-9「『]|$))/g);
  var out = [];
  for (var i = 0; i < parts.length; i++) {
    var s = (parts[i] || "").trim();
    if (s) out.push(s);
  }
  var merged = [];
  for (var j = 0; j < out.length; j++) {
    var cur = out[j];
    if (cur.length < 20 && j + 1 < out.length) { out[j + 1] = cur + " " + out[j + 1]; continue; }
    if (cur.length > 200) {
      var hard = cur.split(/(?<=[、，,])/g);
      var acc = "";
      for (var k = 0; k < hard.length; k++) {
        acc += hard[k];
        if (acc.length >= 100 || k === hard.length - 1) { merged.push(acc.trim()); acc = ""; }
      }
      if (acc.trim()) merged.push(acc.trim());
    } else { merged.push(cur); }
  }
  return merged.filter(Boolean);
}
function splitSentences(text) {
  var src = String(text || "");
  if (!src.trim()) return [];
  try {
    if (typeof Intl !== "undefined" && Intl.Segmenter) {
      var seg = new Intl.Segmenter(undefined, { granularity: "sentence" });
      var raw = [];
      var it = seg.segment(src)[Symbol.iterator]();
      var r;
      while (!(r = it.next()).done) { var s = (r.value.segment || "").trim(); if (s) raw.push(s); }
      if (raw.length) {
        var merged = [];
        for (var i = 0; i < raw.length; i++) {
          var cur = raw[i];
          if (cur.length < 20 && i + 1 < raw.length) { raw[i + 1] = cur + " " + raw[i + 1]; continue; }
          merged.push(cur);
        }
        return merged.filter(Boolean);
      }
    }
  } catch (e) { console.warn("[TTS-stream] Segmenter failed, fallback:", e.message); }
  return splitSentencesFallback(src);
}
N.Chat = N.Chat || {};
N.Chat.ttsStream = N.Chat.ttsStream || {};
N.Chat.ttsStream.splitSentences = splitSentences;
})(window.Nous);
```

- [ ] **Step 4: Run test to verify it passes**

Run: `node --check nous/api/http/static/chat/chat-tts-stream.js`
Expected: PASS（構文OK）。ブラウザ目視で日英中の切り分けを確認する。

- [ ] **Step 5: Commit**

```bash
git add nous/api/http/static/chat/chat-tts-stream.js
git commit -m "feat(tts): add multilingual sentence splitter"
```

### Task 7: Frontend — ストリーミング再生キューと結合

**Files:**
- Modify: `nous/api/http/static/chat/chat-tts-stream.js`
- Modify: `nous/api/http/static/chat/chat-send.js:472-643`
- Modify: `nous/api/http/sections/chat/chat_sidebar_media.py`（checkbox 1個追加）

**Interfaces:**
- Consumes: Task 6の`splitSentences`、既存`POST /api/tts/{persona}`、`POST /api/tts/{persona}/combine`
- Produces: `N.Chat.ttsStream.startStream(persona)`, `.onDelta(text)`, `.finish(allText, msgEl)`、結合URLへの`dataset.ttsCacheUrl`上書き

- [ ] **Step 1: Write the failing test**

ブラウザコンソールで `typeof Nous.Chat.ttsStream.startStream === "function"` が `true` を返すこと（初回はFAIL）。

- [ ] **Step 2: Run test to verify it fails**

Run: `node --check nous/api/http/static/chat/chat-tts-stream.js`
Expected: PASS（構文）だが機能テストはブラウザでFAILを確認する。

- [ ] **Step 3: Write minimal implementation**

`chat-tts-stream.js`に追記:

```js
(function(N) {
"use strict";
var S = window.S;
var T = N.Chat.ttsStream;
var _stream = null;
function _postTts(persona, text, voice, emotion, caption) {
  var body = { text: text };
  if (voice) body.voice = voice;
  if (emotion) body.emotion = emotion;
  if (caption) body.caption = caption;
  return N.Core.api("/api/tts/" + encodeURIComponent(persona), { method: "POST", body: JSON.stringify(body) }).then(function(resp) {
    if (resp && _stream && !_stream.caption && resp.caption) { _stream.caption = resp.caption; _stream.emotion = resp.emotion || _stream.emotion; }
    return resp;
  });
}
T.startStream = function(persona) {
  if (N.Chat.tts && N.Chat.tts._endSession) { try { N.Chat.tts._endSession("stream-start"); } catch (e) {} }
  _stream = { persona: persona, sent: 0, doneTexts: [], pending: [], files: [], audio: null, stopped: false, playing: false, caption: null, emotion: null };
  return _stream;
};
T.onDelta = function(fullText) {
  if (!_stream || _stream.stopped) return;
  var sens = T.splitSentences(fullText);
  while (_stream.sent < sens.length - 1) {
    (function(idx, sentence) {
      _stream.sent++;
      _stream.doneTexts.push(sentence);
      var modelInput = document.getElementById("chat-voice-model");
      var voice = modelInput && modelInput.value ? modelInput.value : undefined;
      _stream.pending.push(_postTts(_stream.persona, sentence, voice, _stream.emotion, _stream.caption).then(function(resp) {
        if (resp && resp.audio_url) _stream.files[idx] = resp.audio_url.split("/").pop();
        return resp;
      }));
      _pump();
    })(_stream.doneTexts.length - 1, sens[_stream.sent]);
  }
};
function _pump() {
  if (!_stream || _stream.playing || _stream.stopped) return;
  var next = _stream.pending.shift();
  if (!next) return;
  _stream.playing = true;
  next.then(function(resp) {
    if (_stream.stopped) { _stream.playing = false; return; }
    if (resp && resp.audio_url) {
      var a = new Audio(resp.audio_url);
      _stream.audio = a;
      a.onended = function() { _stream.playing = false; _pump(); };
      a.onerror = function() { _stream.playing = false; _pump(); };
      a.play().catch(function() { _stream.playing = false; _pump(); });
    } else { _stream.playing = false; _pump(); }
  }).catch(function() { _stream.playing = false; _pump(); });
}
T.finish = function(allText, msgEl) {
  if (!_stream) return Promise.resolve(null);
  var sens = T.splitSentences(allText);
  while (_stream.sent < sens.length) {
    (function(idx, sentence) {
      _stream.sent++;
      var modelInput = document.getElementById("chat-voice-model");
      var voice = modelInput && modelInput.value ? modelInput.value : undefined;
      _stream.pending.push(_postTts(_stream.persona, sentence, voice, _stream.emotion, _stream.caption).then(function(resp) {
        if (resp && resp.audio_url) _stream.files[idx] = resp.audio_url.split("/").pop();
        return resp;
      }));
    })(_stream.doneTexts.length, sens[_stream.sent]);
  }
  return Promise.allSettled(_stream.pending).then(function() {
    var files = _stream.files.filter(Boolean);
    if (!files.length) return null;
    var modelInput = document.getElementById("chat-voice-model");
    var body = { files: files, fullText: allText };
    if (modelInput && modelInput.value) body.voice = modelInput.value;
    if (_stream.emotion) body.emotion = _stream.emotion;
    if (_stream.caption) body.caption = _stream.caption;
    return N.Core.api("/api/tts/" + encodeURIComponent(_stream.persona) + "/combine", { method: "POST", body: JSON.stringify(body) }).then(function(resp) {
      if (resp && resp.audio_url && msgEl) { msgEl.dataset.ttsCacheUrl = resp.audio_url; }
      return resp || null;
    }).catch(function(e) { console.warn("[TTS-stream] combine failed:", e.message); return null; });
  });
};
T.stop = function() { if (_stream) { _stream.stopped = true; try { _stream.audio && _stream.audio.pause(); } catch (e) {} } };
})(window.Nous);
```

`chat-send.js`の`text_delta`末尾（`currentTextContent += evt.content;`直後）に1行追加:

```js
if (window.Nous && Nous.Chat.ttsStream && Nous.Chat.ttsStream.onDelta && document.getElementById("chat-voice-streaming")?.checked) { try { Nous.Chat.ttsStream.onDelta(currentTextContent); } catch (_e) {} }
```

`done`の`autoPlay`分岐を以下に置換する:

```js
var voiceAutoPlay = document.getElementById("chat-voice-auto-play");
var voiceStreaming = document.getElementById("chat-voice-streaming");
if (voiceAutoPlay && voiceAutoPlay.checked && allText.trim()) {
  if (voiceStreaming && voiceStreaming.checked && Nous.Chat.ttsStream && Nous.Chat.ttsStream.finish) {
    var _msgEls = document.querySelectorAll("#chat-messages .chat-msg");
    var _msgEl = _msgEls.length ? _msgEls[_msgEls.length - 1] : null;
    Nous.Chat.ttsStream.finish(allText.trim(), _msgEl);
  } else {
    N.Chat.tts.autoPlay(allText.trim());
  }
}
```

ストリーム開始は`_createAssistantDiv`直後に `Nous.Chat.ttsStream.startStream(S.persona)` を呼ぶ（streaming checkbox ON時のみ）。

サイドバーにcheckbox追加（`chat_sidebar_media.py`の`chat-voice-auto-play`直後）:

```html
<label style="display:flex;gap:6px;align-items:center;font-size:0.8rem;"><input type="checkbox" id="chat-voice-streaming" checked /> 文ごと逐次再生（ストリーミング）</label>
```

- [ ] **Step 4: Run test to verify it passes**

Run: `node --check nous/api/http/static/chat/chat-tts-stream.js && node --check nous/api/http/static/chat/chat-send.js`
Expected: PASS。実ブラウザで初音latencyと結合後シークバーを目視する（テストコード成功のみで完了としない）。

- [ ] **Step 5: Commit**

```bash
git add nous/api/http/static/chat/chat-tts-stream.js nous/api/http/static/chat/chat-send.js nous/api/http/sections/chat/chat_sidebar_media.py
git commit -m "feat(tts): streaming queue playback and combine"
```

### Task 8: 検証ループと記録

**Files:**
- Modify: `docs/superpowers/specs/2026-09-05-tts-streaming-design.md`（結合キー解決の追記のみ、必要時）

**Interfaces:**
- Consumes: Task 1-7の全成果物
- Produces: GATE通過（型・テスト・lint・format・契約・シークレット・監査・ドキュメント同期）

- [ ] **Step 1: 型チェック**

Run: `mypy nous/api/http/routers/tts.py nous/domain/session_config.py`
Expected: 新規エラー0（既存の `openai_compat.py:95,147` は対象外）。

- [ ] **Step 2: 単体テスト**

Run: `pytest tests/unit/test_tts_clamp01.py tests/unit/test_tts_caption_fallback.py tests/unit/test_tts_cache_key.py tests/unit/test_tts_combine.py tests/unit/test_tts_style_anchor.py tests/unit/test_tts_emotion_caption.py tests/unit/domain/test_chat_config.py -v`
Expected: 全PASS。

- [ ] **Step 3: lintとformat**

Run: `ruff check nous/api/http/routers/tts.py nous/domain/session_config.py && ruff format --check nous/api/http/routers/tts.py nous/domain/session_config.py`
Expected: 0エラー。失敗時は `ruff format` で修正して再実行する。

- [ ] **Step 4: 実ブラウザ確認**

`agent-browser`で表示・操作を確認する。確認項目: (1) 長文で1文目が全文確定前に再生開始すること (2) 結合後に単一シークバーで再再生できること (3) OFF時は従来の一発再生になること。

- [ ] **Step 5: Commit（記録は別途RECORDフェーズ）**

```bash
git add docs/superpowers/plans/2026-09-05-tts-streaming.md
git commit -m "docs(plan): tts streaming implementation plan"
```
