# TTS SSE単一化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 文ごとPOSTを廃し、1リクエスト＋SSE中継（`POST /api/tts/{persona}/stream`）に一本化する。

**Architecture:** 字幕LLMはchat開始時にバックエンドで先行起動（personaスロットのTask）。done時にstream EPが字幕Futureを回収（不一致時は直列後退）し、irodori SSEをブラウザへ中継しながらサーバで結合・全文キーcacheする。フロントは`chat-tts-stream.js`をSSE消費者に書換え。

**Tech Stack:** Python (FastAPI/Starlette StreamingResponse, httpx client.stream), 素のJS (fetch reader + Audio), pytest, node --check + /tmpハーネス。

## Global Constraints

- 新規依存なし（stdlib + httpxのみ。httpxは既存）。
- キャッシュキー材料は変更しない（`first_sentence_chunk_min_chars`はキー外と明記）。
- 仕様: `docs/superpowers/specs/2026-09-05-tts-sse-unification-design.md`。
- 1タスク1コミット。RED→GREEN→commitの順を守る。
- 既存テストのFake ctx/stateパターンは流用する（例: `tests/unit/test_tts_caption_fallback.py`）。

---

### Task 1: 字幕解決の抽出 `_resolve_caption`

**Files:**
- Modify: `nous/api/http/routers/tts.py`（先頭import＋新規関数＋`synthesize_tts`の置換）
- Test: `tests/unit/test_tts_caption_resolve.py`（新規）

**Interfaces:**
- Consumes: 既存 `build_style_anchor`, `build_caption_emotion_directive`, `_emotion_bucket`, `_clamp01`, `_intensity_word`, `_LAST_CAPTION`, `_resolve_emotion_mode`, `_resolve_tts_override`（変更なし）。
- Produces: `CaptionResult(emotion, caption, snapshot)` / `CaptionSnapshot(emotion, bucket)` / `async def _resolve_caption(persona, ctx, chat_config, *, ref_text, override_emotion="", override_caption=None) -> CaptionResult`（Task 2・4が使用）。

- [ ] **Step 1: import追加の確認テストは不要。先に失敗テストを書く**

```python
from nous.api.http.routers.tts import CaptionResult, _resolve_caption


def test_off_mode_returns_neutral_without_llm(fake_chat_config_off, fake_ctx):
    import asyncio
    res = asyncio.run(_resolve_caption("herta", fake_ctx, fake_chat_config_off, ref_text="こんにちは"))
    assert isinstance(res, CaptionResult)
    assert res.emotion == "neutral"
    assert res.caption is None
    assert res.snapshot.emotion == "neutral"


def test_override_passthrough_skips_state(fake_ctx, fake_chat_config_llm):
    import asyncio
    # use_override相当: state参照 cop があっても呼ばれない（ FakeCtx.get_contextにbombを仕込む ）
    res = asyncio.run(
        _resolve_caption("herta", fake_ctx, fake_chat_config_llm,
                         ref_text="本文", override_emotion="joy", override_caption="明るく話す。")
    )
    assert res.emotion == "joy"
    assert res.caption == "明るく話す。"
```

- [ ] **Step 2: 実行してFAILを確認**

Run: `pytest tests/unit/test_tts_caption_resolve.py -v`
Expected: FAIL with "cannot import name '_resolve_caption'"（Fake fixture名は既存TTSテストのものに合わせる）

- [ ] **Step 3: 実装。まず先頭importを変更**

```python
from typing import TYPE_CHECKING, NamedTuple
```

```python
import asyncio
import base64
```

（`import asyncio`は`import base64`の前。アルファベット順。）

次に`_LAST_CAPTION`定義（94行目付近）の直後に追加：

```python
class CaptionSnapshot(NamedTuple):
    emotion: str
    bucket: float


class CaptionResult(NamedTuple):
    emotion: str
    caption: str | None
    snapshot: CaptionSnapshot
```

次に`_resolve_tts_override`の後（136行目付近）に抽出関数を追加。内容は現行`synthesize_tts`の300〜407行目をそのまま移す。ただし`text`変数は引数`ref_text`に置換し、`use_override`分岐は引数で受ける：

```python
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
            caption = build_style_anchor(
                emotion,
                float(state.emotion_intensity or 0.0),
                appearance=getattr(state, "appearance", None),
                relationship=getattr(state, "relationship_status", None),
            )
    snapshot = CaptionSnapshot(
        emotion, _emotion_bucket(float(getattr(state, "emotion_intensity", 0.0) or 0.0)) if state else _emotion_bucket(0.0)
    )
    if mode == "llm" and state:
        # 以下は現行322〜407行目と同一。llm_user内の {text} は ref_text に置換。
        # （provider取得・_LAST_CAPTION・ErrorEvent/saw_error処理は一字一句そのまま移す）
        ...
    return CaptionResult(emotion, caption, snapshot)
```

`synthesize_tts`側（300〜407行目）を置換：

```python
        # get persona state for emotion + build caption
        ov_emo, ov_cap, use_override = _resolve_tts_override(body)
        caption_res = await _resolve_caption(
            persona,
            ctx,
            chat_config,
            ref_text=text,
            override_emotion=ov_emo if use_override else "",
            override_caption=ov_cap if use_override else None,
        )
        emotion, caption = caption_res.emotion, caption_res.caption
```

注意：`state`変数はsynthesize内で他に使われていない（410行目以降は使わない）。`emotion_mode`変数も削除してよい（他で参照なし）。

- [ ] **Step 4: 実行してPASSを確認**

Run: `pytest tests/unit/test_tts_caption_resolve.py tests/unit/test_tts_caption_fallback.py tests/unit/test_tts_caption_override.py tests/unit/test_tts_emotion_caption.py tests/unit/test_tts_style_anchor.py -v`
Expected: 全PASS（既存の振る舞い不変がここで証明される）

- [ ] **Step 5: Commit**

```bash
git add nous/api/http/routers/tts.py tests/unit/test_tts_caption_resolve.py
git commit -m "refactor(tts): extract _resolve_caption for serial/parallel reuse"
```

---

### Task 2: 字幕先行kickoff＋chatフック

**Files:**
- Modify: `nous/api/http/routers/tts.py`（`_CAPTION_TASKS`＋2関数を`_LAST_CAPTION`付近に追加）
- Modify: `nous/api/http/routers/chat/chat_stream.py`（`chat_endpoint`のbody検証後、`return StreamingResponse`の直前にkickoff呼出し）
- Test: `tests/unit/test_tts_caption_kickoff.py`（新規）

**Interfaces:**
- Consumes: Task 1の`_resolve_caption`, `_resolve_emotion_mode`。
- Produces: `_CAPTION_TASKS: dict[str, asyncio.Task]` / `kickoff_caption_task(persona, ctx, user_message) -> None` / `take_caption_task(persona)`（Task 4が使用）。

- [ ] **Step 1: 失敗テストを書く**

```python
import asyncio
from nous.api.http.routers import tts as tts_mod


def test_kickoff_skips_non_llm_modes(fake_ctx, fake_chat_config_off):
    tts_mod.kickoff_caption_task("herta", fake_ctx, "こんにちは")
    assert tts_mod.take_caption_task("herta") is None


def test_kickoff_starts_task_in_llm_mode(fake_ctx, fake_chat_config_llm):
    tts_mod.kickoff_caption_task("herta", fake_ctx, "こんにちは")
    task = tts_mod.take_caption_task("herta")
    assert task is not None
    if not task.done():
        task.cancel()
    # takeはpopする（2回目はNone）
    assert tts_mod.take_caption_task("herta") is None


def test_kickoff_cancels_previous(fake_ctx, fake_chat_config_llm):
    tts_mod.kickoff_caption_task("herta", fake_ctx, "1回目")
    first = tts_mod.take_caption_task("herta")
    # 取り出さず2回目を蹴る状況の再現：もう一度kickoff
    tts_mod.kickoff_caption_task("herta", fake_ctx, "1回目")
    tts_mod.kickoff_caption_task("herta", fake_ctx, "2回目")
    second = tts_mod.take_caption_task("herta")
    assert second is not None
    for t in (first, second):
        if t is not None and not t.done():
            t.cancel()
```

注意：`kickoff_caption_task`は`asyncio.get_running_loop()`を使うため、テストは`asyncio.run()`の中で呼ぶか、`pytest.mark.asyncio`で書く。リポジトリにasyncioプラグイン設定がなければ`asyncio.run(inner())`形式にする（既存TTSテストは`asyncio.run`形式のはず。合わせる）。

- [ ] **Step 2: 実行してFAILを確認**

Run: `pytest tests/unit/test_tts_caption_kickoff.py -v`
Expected: FAIL with "cannot import name" または attribute error

- [ ] **Step 3: 実装。tts.pyの`_LAST_CAPTION`（94行目）の直後に追加**

```python
_CAPTION_TASKS: dict[str, asyncio.Task] = {}


def kickoff_caption_task(persona: str, ctx, user_message: str) -> None:
    """chat開始時に字幕LLMを先行開始する。llmモード以外は何もしない。旧タスクは取消。"""
    prev = _CAPTION_TASKS.pop(persona, None)
    if prev is not None and not prev.done():
        prev.cancel()
    try:
        from nous.config.settings import get_settings
        from nous.domain.chat_config import ChatConfigFileRepository

        chat_config = ChatConfigFileRepository(get_settings().data_root).get(persona)
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
```

chat_stream.pyの`chat_endpoint`内、`if not user_message:`ブロック（118〜119行目）の直後、`return StreamingResponse(`（121行目）の直前に追加：

```python
    try:
        from nous.api.http.routers.tts import kickoff_caption_task

        kickoff_caption_task(persona, ctx, user_message)
    except Exception:
        logger.exception("chat_endpoint: caption kickoff failed")
```

循環importなし（tts.pyはchat_streamをimportしていない。関数内遅延importなので安全）。

- [ ] **Step 4: 実行してPASSを確認**

Run: `pytest tests/unit/test_tts_caption_kickoff.py tests/unit/test_tts_caption_resolve.py -v`
Expected: PASS。未完了Taskの警告（"Task was destroyed"）が出たらテスト内でcancel＋awaitして消す。

- [ ] **Step 5: Commit**

```bash
git add nous/api/http/routers/tts.py nous/api/http/routers/chat/chat_stream.py tests/unit/test_tts_caption_kickoff.py
git commit -m "feat(tts): parallel caption kickoff at chat start"
```

---

### Task 3: エンジンSSE＋first_sentence設定

**Files:**
- Modify: `nous/config/settings.py`（`IrodoriAdvancedParams`に1フィールド追加）
- Modify: `nous/api/http/routers/tts.py`（`_get_irodori_config`で新値を渡す）
- Modify: `nous/infrastructure/voice/irodori.py`（payload builder抽出＋`stream_speech`追加）
- Test: `tests/unit/test_voice.py`（既存にSSEケース追加）または新規`tests/unit/test_voice_stream.py`
- Test: キー安定テスト（`tests/unit/test_tts_cache_key.py`に1件追加）

**Interfaces:**
- Consumes: 既存`IrodoriConfig/_voice/_timeout/_advanced`。
- Produces: `async def IrodoriEngine.stream_speech(text, emotion, caption=None, speed=None)`（wav bytesをyieldするasync generator。単発・リトライなし）（Task 4が使用）。

- [ ] **Step 1: 失敗テストを書く（SSE正常系＋キー安定）**

```python
import asyncio
import httpx
from nous.infrastructure.voice.irodori import IrodoriEngine


def _sse_transport(chunks: list[bytes]):
    async def handler(request: httpx.Request) -> httpx.Response:
        body = (
            b'data: {"type": "audio_chunk", "audio_base64": "%s"}\n\n' % chunks[0]
            + b'data: {"type": "audio_chunk", "audio_base64": "%s"}\n\n' % chunks[1]
            + b'data: {"type": "done"}\n\n'
        )
        return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})
    return httpx.MockTransport(handler)


def test_stream_speech_yields_chunks_and_sends_sse_params(fake_irodori_config):
    import base64
    c1 = base64.b64encode(b"wav1").decode()
    c2 = base64.b64encode(b"wav2").decode()
    seen: dict = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        import json
        seen.update(json.loads(request.content.decode()))
        body = (
            ('data: {"type": "audio_chunk", "audio_base64": "%s"}\n\n' % c1).encode()
            + ('data: {"type": "audio_chunk", "audio_base64": "%s"}\n\n' % c2).encode()
            + b'data: {"type": "done"}\n\n'
        )
        return httpx.Response(200, content=body)

    engine = IrodoriEngine(fake_irodori_config)
    # MockTransport差替え: engine内部でAsyncClientを作るため、httpx.AsyncClientをpatchする
    ...
```

注意：現行`synthesize`は内部で`httpx.AsyncClient`を直接生成するため、MockTransportを差すには`unittest.mock.patch("httpx.AsyncClient", ...)`か、既存`test_voice.py`のmock手法を流用する。既存手法を先に読み、合わせること（RED記述は既存流儀に従う）。

キー安定テスト（`tests/unit/test_tts_cache_key.py`に追記）：

```python
def test_cache_key_ignores_chunking_params():
    from nous.api.http.routers.tts import _tts_cache_key
    base = dict(text="あ", emotion="neutral", caption=None, voice_speed=1.0,
                voice_override=None, voice_resolved="v", model="irodori-tts",
                seed=0, num_steps=30, cfg_text=3.2, cfg_speaker=5.0,
                cfg_caption=4.2, chunk_min_chars=85)
    k1 = _tts_cache_key(**base)
    k2 = _tts_cache_key(**base)
    assert k1 == k2 and len(k1) == 64
    # _tts_cache_keyの引数に first_sentence_chunk_min_chars が存在しないこと（キー外のlock-in）
    import inspect
    assert "first_sentence" not in inspect.signature(_tts_cache_key).parameters
```

- [ ] **Step 2: 実行してFAILを確認**

Run: `pytest tests/unit/test_voice_stream.py tests/unit/test_tts_cache_key.py -v`
Expected: FAIL（`stream_speech`未定義）

- [ ] **Step 3: 実装**

settings.pyの`seed`フィールド（172〜173行目）の直後に追加：

```python
    first_sentence_chunk_min_chars: int = 1
    """First-sentence fast-path chunk threshold for SSE. Range: 1-200."""
```

settings.pyの`chunk_min_chars`（169〜170行目）の既定を85→40に変更（改行の間を残すため。docstringのRange表記30-200はそのまま。値ズレで旧cacheは孤児化し一度だけ再合成される）：

```python
    chunk_min_chars: int = 40
```

tts.pyの`_get_irodori_config`（208〜215行目）のgetattr既定も85→40に合わせる（settings既定と不一致だと設定未指定時に40にならない）：

```python
        chunk_min_chars=getattr(chat_config, "irodori_chunk_min_chars", 40),
```

さらに`_get_irodori_config`（208〜215行目）に1行追加：

```python
        first_sentence_chunk_min_chars=getattr(chat_config, "irodori_first_sentence_chunk_min_chars", 1),
```

irodori.py：payload組立て（49〜71行目）を`_build_payload`に抽出し、`stream_format`と`first_sentence_chunk_min_chars`はstream時のみ付与：

```python
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
```

`synthesize`は`payload = self._build_payload(text, emotion, caption, speed)`に置換（49〜71行目削除）。既存payload形状テストはそのまま通ること。

`stream_speech`を`synthesize`の後に追加：

```python
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
            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream("POST", f"{self._url}/v1/audio/speech", json=payload) as resp:
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
                                yield base64.b64decode(b64)
                            except (ValueError, binascii.Error):
                                continue
                        etype = str(evt.get("type") or evt.get("event") or "")
                        if etype in ("done", "error", "end", "complete"):
                            break
        except httpx.HTTPStatusError as e:
            raise RuntimeError(f"Irodori TTS stream HTTP {e.response.status_code}") from e
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            raise RuntimeError("Irodori TTS stream failed") from e
```

- [ ] **Step 4: 実行してPASSを確認**

Run: `pytest tests/unit/test_voice.py tests/unit/test_voice_stream.py tests/unit/test_tts_cache_key.py -v`
Expected: PASS（既存payload形状テストが通る＝synthesize無改変の証明）

- [ ] **Step 5: Commit**

```bash
git add nous/config/settings.py nous/api/http/routers/tts.py nous/infrastructure/voice/irodori.py tests/unit/test_voice_stream.py tests/unit/test_tts_cache_key.py
git commit -m "feat(tts): engine SSE streaming with first-sentence fast path"
```

---

### Task 4: `POST /stream` 中継エンドポイント

**Files:**
- Modify: `nous/api/http/routers/tts.py`（先頭importに`StreamingResponse`追加＋`_relay_tts_stream`＋`/stream`ルートを`register_tts_routes`内に追加）
- Test: `tests/unit/test_tts_stream_endpoint.py`（新規）

**Interfaces:**
- Consumes: Task 1（`_resolve_caption`）・Task 2（`take_caption_task`）・Task 3（`engine.stream_speech`）、既存`_tts_cache_key/_find_cache_file/_concat_wav/health_check流儀/voice override/speed_arg`。
- Produces: SSEイベント `tts_chunk{seq,audio_base64}` / `tts_done{audio_url}` / `tts_error{message}`（Task 5のフロントが消費）。

- [ ] **Step 1: 失敗テストを書く**

```python
def test_stream_hit_returns_single_chunk_and_done(client, seeded_cache):
    # 全文キーHIT時：tts_chunk 1件＋tts_done(audio_url付き)。合成は呼ばれない。
    ...


def test_stream_miss_relays_and_caches(client, stub_engine):
    # engine.stream_speechが2チャンクyield → tts_chunk×2＋tts_done。cacheファイルが全文キーで書かれる。
    ...


def test_stream_mid_error_writes_no_cache(client, failing_engine):
    # 1チャンク後に例外 → tts_chunk×1＋tts_error。doneなし・cacheファイルなし。
    ...
```

テストTokenzier：既存のsynthesizeエンドポイントテスト（TestClient利用のはず）のfixture流儀を流用する。engine差替えは`nous.api.http.routers.tts.get_voice_engine`をpatchする。`take_caption_task`はNoneを返すようpatchし、直列resolve経路（off/anchor設定）でLLMなしに通す。

- [ ] **Step 2: 実行してFAILを確認**

Run: `pytest tests/unit/test_tts_stream_endpoint.py -v`
Expected: FAIL（404：ルート未定義）

- [ ] **Step 3: 実装**

先頭import変更：

```python
from starlette.responses import FileResponse, JSONResponse, Response, StreamingResponse
```

`_find_cache_file`の後あたり（モジュールレベル、`register_tts_routes`の前）に中継generator：

```python
async def _relay_tts_stream(engine, *, text, emotion, caption, speed_arg, cache_path, audio_url):
    """irodori SSEを中継しつつ蓄積→完了時に結合・保存。途中失敗はcache書込なし・doneなし。"""
    import tempfile

    chunks: list[bytes] = []
    seq = 0
    try:
        async for wav in engine.stream_speech(text=text, emotion=emotion, caption=caption, speed=speed_arg):
            chunks.append(wav)
            yield f"data: {json.dumps({'type': 'tts_chunk', 'seq': seq, 'audio_base64': base64.b64encode(wav).decode('ascii')}, separators=(',', ':'))}\n\n"
            seq += 1
    except Exception as e:
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
    except ValueError as e:
        logger.exception("TTS stream combine failed")
        yield f"data: {json.dumps({'type': 'tts_error', 'message': 'combine failed'}, separators=(',', ':'))}\n\n"
        return
    cache_path.write_bytes(combined)
    yield f"data: {json.dumps({'type': 'tts_done', 'audio_url': audio_url}, separators=(',', ':'))}\n\n"
```

`register_tts_routes`内に`synthesize_tts`の後、`health_check_tts`の前に`/stream`ルート追加。骨格（health・body・voice・speed・cache keyはsynthesizeと同一流儀）：

```python
    @mcp.custom_route("/api/tts/{persona}/stream", methods=["POST"])
    async def stream_tts(request: Request) -> Response:
        persona = _resolve_persona_from_request(request)
        ctx = _safe_get_context(persona)
        if not ctx:
            return JSONResponse({"ok": False, "error": "Persona not found"}, status_code=404)

        from nous.config.settings import get_settings
        from nous.domain.chat_config import ChatConfigFileRepository

        chat_config = ChatConfigFileRepository(get_settings().data_root).get(persona)
        irodori_config = _get_irodori_config(ctx, chat_config)
        engine = get_voice_engine(irodori_config)

        try:
            ok = await engine.health_check()
            if not ok:
                return JSONResponse({"ok": False, "error": "Voice engine health check failed"}, status_code=503)
        except Exception:
            return JSONResponse({"ok": False, "error": "Voice engine unreachable"}, status_code=503)

        try:
            body = await request.json()
        except (json.JSONDecodeError, TypeError):
            body = {}
        if not isinstance(body, dict):
            body = {}
        text = _body_text_required(body, "text")
        if not text:
            return JSONResponse({"ok": False, "error": "text is required"}, status_code=400)

        voice_override = _body_str(body, "voice") or (chat_config.voice_model or None)
        if voice_override:
            from nous.infrastructure.voice.irodori import IrodoriEngine

            if isinstance(engine, IrodoriEngine):
                engine._voice = voice_override  # noqa: SLF001

        voice_speed = float(getattr(chat_config, "voice_speed", 1.0) or 1.0)
        speed_arg = None if abs(voice_speed - 1.0) < 1e-9 else voice_speed
        voice_resolved = voice_override or chat_config.voice_model or ctx.settings.irodori.voice

        # 字幕：並列タスク回収 → 不一致/失敗時は直列後退
        caption_res = await _resolve_caption(persona, ctx, chat_config, ref_text=text)
        task = take_caption_task(persona)
        if task is not None:
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
        emotion, caption = caption_res.emotion, caption_res.caption

        settings = get_settings()
        cache_dir = Path(settings.data_root) / "persona" / persona / "tts_cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_key = _tts_cache_key(
            text=text, emotion=emotion, caption=caption, voice_speed=voice_speed,
            voice_override=voice_override, voice_resolved=voice_resolved,
            model=irodori_config.model, seed=irodori_config.advanced.seed,
            num_steps=irodori_config.advanced.num_steps,
            cfg_text=irodori_config.advanced.cfg_scale_text,
            cfg_speaker=irodori_config.advanced.cfg_scale_speaker,
            cfg_caption=irodori_config.advanced.cfg_scale_caption,
            chunk_min_chars=irodori_config.advanced.chunk_min_chars,
        )
        new_cache_path = cache_dir / f"{cache_key}.wav"
        found_path, audio_url_filename = _find_cache_file(cache_dir, cache_key)
        audio_url = f"/api/tts/{persona}/cache/{audio_url_filename}"

        if found_path:
            blob = found_path.read_bytes()

            async def _hit():
                yield f"data: {json.dumps({'type': 'tts_chunk', 'seq': 0, 'audio_base64': base64.b64encode(blob).decode('ascii')}, separators=(',', ':'))}\n\n"
                yield f"data: {json.dumps({'type': 'tts_done', 'audio_url': audio_url}, separators=(',', ':'))}\n\n"

            return StreamingResponse(_hit(), media_type="text/event-stream; charset=utf-8")

        return StreamingResponse(
            _relay_tts_stream(
                engine, text=text, emotion=emotion, caption=caption,
                speed_arg=speed_arg, cache_path=new_cache_path, audio_url=audio_url,
            ),
            media_type="text/event-stream; charset=utf-8",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
```

注意：`asyncio.wait_for(task, ...)`のタイムアウト時はtaskがcancelされる（LLMコスト節約になる）。taskが例外保持の場合は`await`でraise→exceptで直列後退（既に得たcaption_resを使う）。どちらも正しい。

- [ ] **Step 4: 実行してPASSを確認**

Run: `pytest tests/unit/test_tts_stream_endpoint.py tests/unit/test_tts_caption_kickoff.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add nous/api/http/routers/tts.py tests/unit/test_tts_stream_endpoint.py
git commit -m "feat(tts): single-request SSE relay endpoint with server combine"
```

---

### Task 5: フロント書換え（SSE消費者）

**Files:**
- Modify: `nous/api/http/static/chat/chat-tts-stream.js`（全面書換え。同一パス・同一公開関数名）
- Test: `/tmp/tts-sse-harness.js`（新規nodeハーネス）
- chat-send.jsの変更なし（491行目の`onDelta`呼出しは`onDelta`未定義で inert になる。224行目`startStream`・645〜648行目`finish`分岐はそのまま使う）

**Interfaces:**
- Consumes: Task 4のSSEイベント。既存`N.Chat.tts.stripMarkdown` / `N.Chat.tts.getVolume` / `N.Chat.tts._endSession` / `#chat-voice-model`（変更なし）。
- Produces: `T.startStream(persona)` / `T.finish(allText, msgEl) -> Promise` / `T.stop()`（chat-send.jsの既存呼出しと同一signature）。

- [ ] **Step 1: ハーネスを書く（RED）。fetch/Audio/documentの最小stub＋5ケース**

```js
// /tmp/tts-sse-harness.js — node実行。chat-tts-stream.jsを読み込んで振る舞い検証。
const fs = require("fs");
const src = fs.readFileSync("nous/api/http/static/chat/chat-tts-stream.js", "utf8");
let played = [];
global.Audio = function(url) { this.url = url; this.volume = 1.0; };
global.Audio.prototype.play = function() { played.push(this.url); if (this.onended) this.onended(); return Promise.resolve(); };
global.Audio.prototype.pause = function() {};
// ... fetch stub（シナリオ別にSSEバイト列を返すReaderもどき）、document stub（getElementById→null）、
// window.Nous / N.Core / N.Chat.tts（stripMarkdown恒等・getVolume→0.5・_endSession記録）を用意し、
// T.startStream→T.finish→ played順序・msgEl.dataset・stop後の無音をassertする5ケース。
```

ケース：①chunk順再生 ②doneでdataset.ttsCacheUrl設定 ③errorでnull解決＋警告 ④空文でfetchなしnull ⑤stopで中断。各ケースは旧ハーネス（`/tmp/tts-stream-harness.js`）のstub流儀を流用してよい。

- [ ] **Step 2: 実行してFAILを確認**

Run: `node /tmp/tts-sse-harness.js`
Expected: FAIL（現行ファイルは旧関数群のため。例：`T.finish is not a function`等ではなく、旧finishがcombineを呼ぶためfetch-stub不一致でFAILする。いずれにせよ赤を確認）

- [ ] **Step 3: 実装。chat-tts-stream.jsを以下で全面置換**

```js
/* CHAT TTS STREAM — single-request SSE relay playback */
(function(N) {
"use strict";
var T = N.Chat.ttsStream = N.Chat.ttsStream || {};
var _stream = null;
function _voiceInput() {
  var el = document.getElementById("chat-voice-model");
  return (el && el.value) ? el.value : undefined;
}
function _strip(text) {
  var t = String(text || "");
  try {
    var f = N.Chat && N.Chat.tts && N.Chat.tts.stripMarkdown;
    if (typeof f === "function") t = f(text);
  } catch (e) {}
  if (!/[\p{L}\p{N}]/u.test(t)) return "";
  return t;
}
function _playNext(stream) {
  if (!stream || stream.stopped || stream.playing) return;
  var url = stream.queue.shift();
  if (!url || stream !== _stream) return;
  stream.playing = true;
  var a = new Audio(url);
  try {
    var g = N.Chat.tts && N.Chat.tts.getVolume;
    a.volume = (typeof g === "function") ? g() : 1.0;
  } catch (_e) {}
  stream.audio = a;
  a.onended = function() { stream.playing = false; _playNext(stream); };
  a.onerror = function() { stream.playing = false; _playNext(stream); };
  try {
    var p = a.play();
    if (p && p.catch) p.catch(function() { stream.playing = false; _playNext(stream); });
  } catch (_e2) { stream.playing = false; _playNext(stream); }
}
T.startStream = function(persona) {
  if (N.Chat.tts && N.Chat.tts._endSession) { try { N.Chat.tts._endSession("stream-start"); } catch (e) {} }
  if (_stream) { try { T.stop(); } catch (_e2) {} }
  _stream = { persona: persona, stopped: false, audio: null, ctrl: null, queue: [], playing: false, done: false };
  return _stream;
};
T.finish = function(allText, msgEl) {
  var stream = _stream;
  if (!stream) return Promise.resolve(null);
  var text = _strip(allText);
  if (!text) return Promise.resolve(null);
  var ctrl = (typeof AbortController !== "undefined") ? new AbortController() : null;
  stream.ctrl = ctrl;
  var body = { text: text };
  var v = _voiceInput();
  if (v) body.voice = v;
  return fetch("/api/tts/" + encodeURIComponent(stream.persona) + "/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal: ctrl ? ctrl.signal : undefined
  }).then(function(resp) {
    if (!resp.ok) throw new Error("HTTP " + resp.status);
    var reader = resp.body.getReader();
    var decoder = new TextDecoder();
    var buf = "";
    var result = null;
    function onEvent(obj) {
      if (!obj || stream !== _stream || stream.stopped) return;
      if (obj.type === "tts_chunk" && obj.audio_base64) {
        try {
          var bin = atob(obj.audio_base64);
          var bytes = new Uint8Array(bin.length);
          for (var i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
          stream.queue.push(URL.createObjectURL(new Blob([bytes], { type: "audio/wav" })));
          _playNext(stream);
        } catch (_e) {}
      } else if (obj.type === "tts_done") {
        stream.done = true;
        if (obj.audio_url && msgEl) { try { msgEl.dataset.ttsCacheUrl = obj.audio_url; } catch (_e2) {} }
        result = obj;
      } else if (obj.type === "tts_error") {
        if (typeof console !== "undefined") console.warn("[TTS-stream]", obj.message || "stream error");
      }
    }
    function pump() {
      return reader.read().then(function(r) {
        if (r.done) return result;
        buf += decoder.decode(r.value, { stream: true });
        var lines = buf.split("\n");
        buf = lines.pop();
        for (var i = 0; i < lines.length; i++) {
          if (lines[i].indexOf("data: ") !== 0) continue;
          try { onEvent(JSON.parse(lines[i].slice(6))); } catch (_e) {}
        }
        return pump();
      });
    }
    return pump();
  }).catch(function(e) {
    if (e && e.name === "AbortError") return null;
    if (typeof console !== "undefined") console.warn("[TTS-stream] fetch failed:", e && e.message);
    return null;
  });
};
T.stop = function() {
  var stream = _stream;
  if (!stream) return;
  stream.stopped = true;
  stream.queue = [];
  try { if (stream.ctrl) stream.ctrl.abort(); } catch (e) {}
  try { if (stream.audio) stream.audio.pause(); } catch (_e) {}
};
})(window.Nous);
```

削除される旧要素：`splitSentences`/`splitSentencesFallback`・`_postTts`・`_advance`・`_enqueue`・`_flushHeld`・`_commonPrefix`・`_nextSentence`・`_send`・`/combine`呼出し・`files[]`/`held[]`。`_stripForTts`は`_strip`に改名継続。

- [ ] **Step 4: 実行してPASSを確認**

Run: `node --check nous/api/http/static/chat/chat-tts-stream.js && node /tmp/tts-sse-harness.js`
Expected: 両方PASS（5ケース）

- [ ] **Step 5: Commit**

```bash
git add nous/api/http/static/chat/chat-tts-stream.js
git commit -m "feat(tts): frontend SSE relay playback, drop sentence queue"
```

---

### Task 6: 旧経路の削除

**Files:**
- Modify: `nous/api/http/routers/tts.py`（`combine_tts`ルート＝570〜644行目を削除）
- Modify: combineエンドポイントのテストを削除（`grep -rn "/combine" tests/`で特定し、エンドポイント呼出しテストのみ削除。`_concat_wav`直接呼出しの単体テストは残す）
- 文キャッシュのコード削除なし（synthesize経路＝旧一括フォールバック＋🔊手動再生が使い続ける。新規の文エントリは作られなくなり自然淘汰）

**Interfaces:**
- Consumes: Task 4・5完了（/combineの 호출者がゼロになったこと）。
- Produces: 死コードなしのtts.py。

- [ ] **Step 1: 呼出しゼロの確認（REDの代わり）**

Run: `grep -rn "combine" nous/api/http/static/ | grep -v ".map"`
Expected: `/combine`へのfetchがゼロ件（Task 5で消えていることの確認）。残っていたらTask 5に戻る。

- [ ] **Step 2: テスト削除の特定**

Run: `grep -rn "/combine" tests/`
Expected: 一覧が出る。`_concat_wav`を直接呼ぶテスト（ファイル名にconcatを含む等）は残し、HTTP `/combine`を叩くテストのみ削除する。

- [ ] **Step 3: 実装。tts.pyの`combine_tts`全体（`@mcp.custom_route("/api/tts/{persona}/combine"`から`return JSONResponse({"ok": True, "audio_url"...`の終わりまで）を削除。テストファイルから該当テストを削除。**

- [ ] **Step 4: 実行してPASSを確認**

Run: `pytest tests/unit/test_tts_stream_endpoint.py tests/unit/test_tts_combine.py -v`
Expected: PASS（`test_tts_combine.py`が丸ごと消える場合はファイル不存在でよい。その場合は`_concat_wav`の単体テストが消えていないか確認し、消えていたら`tests/unit/test_tts_concat_wav.py`として復元する）

- [ ] **Step 5: Commit**

```bash
git add nous/api/http/routers/tts.py tests/
git commit -m "chore(tts): remove combine endpoint absorbed by stream relay"
```

---

### Task 7: 最終ゲート検証

**Files:** 変更なし（検証のみ。失敗時は該当Taskに戻る）

- [ ] **Step 1: pytest TTS全セット**

Run: `pytest tests/unit/test_tts_caption_resolve.py tests/unit/test_tts_caption_kickoff.py tests/unit/test_tts_stream_endpoint.py tests/unit/test_voice.py tests/unit/test_voice_stream.py tests/unit/test_tts_cache_key.py tests/unit/test_tts_caption_fallback.py tests/unit/test_tts_caption_override.py tests/unit/test_tts_emotion_caption.py tests/unit/test_tts_style_anchor.py tests/unit/test_tts_clamp01.py -v`
Expected: 全PASS。存在しないファイル名があればその時点の実ファイル一覧に置換する（`ls tests/unit/test_tts*`）。

- [ ] **Step 2: ruff**

Run: `ruff check nous/api/http/routers/tts.py nous/api/http/routers/chat/chat_stream.py nous/infrastructure/voice/irodori.py nous/config/settings.py tests/unit/test_tts_caption_resolve.py tests/unit/test_tts_caption_kickoff.py tests/unit/test_tts_stream_endpoint.py tests/unit/test_voice_stream.py`
Expected: PASS。既存指摘（`Failure[DomainError].value`型エラー・旧テストのruff等）は対象外。`ruff format --check`は差分が自Task範囲に閉じる場合のみ適用する。

- [ ] **Step 3: JS**

Run: `node --check nous/api/http/static/chat/chat-tts-stream.js && node /tmp/tts-sse-harness.js`
Expected: PASS

- [ ] **Step 4: mypy影響確認（参考）**

Run: `mypy nous/api/http/routers/tts.py`（リポジトリ設定に従う。439件の既存エラーの中に新規が混ざっていないことを目視確認。新規があれば該当Taskに戻る）

- [ ] **Step 5: Commitは不要（検証のみ）。結果を報告する。**

---

## Self-Review

1. **Spec coverage:** 並列字幕（Task 2＋4）／サーバ結合・維持（Task 4の`_relay_tts_stream`＋全文キーcache）／失敗時ポリシー（Task 4のtts_error＋cache不書込＋🔊は旧一括POSTに後退）／SSE不可時の旧一括後退（chat-send.js分岐は既存のまま）／廃止物（Task 5・6）／テスト（各Task）——対応Taskあり。health checkはstream EPにも維持（spec沈黙点の明示化。1RTTで単発のため速度影響は無視できる）。
2. **Placeholder scan:** コードブロックは全て実コード。`...`はTask 1のllm磨き部のみで「現行322〜407行目を一字一句移す」と明記済み。`fake_*` fixtureは既存ファイル参照を明記。
3. **Type consistency:** `CaptionResult/snapshot`の型はTask 1定義→Task 2・4で同一名使用。SSEイベント名`tts_chunk/tts_done/tts_error`はTask 4・5で一致。`take_caption_task`のpop意味はTask 2・4で一致。`first_sentence_chunk_min_chars`はキー外（Task 3テストでlock-in）。
