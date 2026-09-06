import base64
import io
import json
import types
import wave

import pytest

pytestmark = pytest.mark.unit
from nous.api.http.routers import tts as tts_mod


def _routes():
    captured = {}

    class _MCP:
        def custom_route(self, path, methods):
            def deco(fn):
                captured[(path, tuple(methods))] = fn
                return fn

            return deco

    tts_mod.register_tts_routes(_MCP())
    return captured


def _req(body):
    async def _json():
        return body

    return types.SimpleNamespace(path_params={"persona": "herta"}, headers={}, query_params={}, json=_json)


def _wav_blob(frames: bytes) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(frames)
    return buf.getvalue()


def _fake_ctx(monkeypatch, tmp_path, engine, *, mode="off", state=None, task=None):
    chat_cfg = types.SimpleNamespace(
        voice_model="",
        voice_url="",
        voice_speed=1.0,
        voice_emotion_mode=mode,
        voice_emotion_link=False,
        irodori_caption_llm_enabled=False,
        provider="x",
        model="m",
        api_key="",
        base_url="",
        irodori_caption_llm_model="",
        irodori_num_steps=30,
        irodori_cfg_scale_text=3.2,
        irodori_cfg_scale_speaker=5.0,
        irodori_cfg_scale_caption=4.2,
        irodori_chunk_min_chars=40,
        irodori_first_sentence_chunk_min_chars=1,
        irodori_seed=0,
    )
    import nous.domain.chat_config as chat_config_mod

    monkeypatch.setattr(
        chat_config_mod, "ChatConfigFileRepository", lambda root: types.SimpleNamespace(get=lambda persona: chat_cfg)
    )
    monkeypatch.setattr(
        "nous.config.settings.get_settings",
        lambda: types.SimpleNamespace(data_root=str(tmp_path)),
    )
    fake_ctx = types.SimpleNamespace(
        settings=types.SimpleNamespace(
            irodori=types.SimpleNamespace(url="http://127.0.0.1:9", voice="v", model="m", timeout_seconds=5)
        ),
        persona_service=types.SimpleNamespace(
            get_context=lambda persona: types.SimpleNamespace(is_ok=True, value=state)
        ),
    )
    monkeypatch.setattr(tts_mod, "_safe_get_context", lambda persona: fake_ctx)
    monkeypatch.setattr(tts_mod, "get_voice_engine", lambda cfg: engine)
    monkeypatch.setattr(tts_mod, "take_caption_task", lambda persona: task)


async def _collect_sse(resp):
    raw = []
    async for c in resp.body_iterator:
        raw.append(c.decode() if isinstance(c, bytes) else c)
    body = "".join(raw)
    events = []
    for block in body.split("\n\n"):
        for line in block.split("\n"):
            if line.startswith("data:"):
                events.append(json.loads(line[5:].strip()))
    return events


class _StubEngine:
    def __init__(self, blobs):
        self._blobs = blobs
        self.calls = 0

    async def health_check(self):
        return True

    async def stream_speech(self, **kw):
        self.calls += 1
        for b in self._blobs:
            yield b


class _FailingEngine:
    def __init__(self, blobs):
        self._blobs = blobs

    async def health_check(self):
        return True

    async def stream_speech(self, **kw):
        yield self._blobs[0]
        raise RuntimeError("boom")


async def test_stream_hit_returns_single_chunk_and_done(monkeypatch, tmp_path):
    blob = _wav_blob(b"\x01\x02" * 800)
    stub = _StubEngine([blob])
    _fake_ctx(monkeypatch, tmp_path, stub)
    fn = _routes()[("/api/tts/{persona}/stream", ("POST",))]
    # 1回目MISSでcache作成 → engineをbombに差替えてHITを確認
    resp = await fn(_req({"text": "こんにちは"}))
    assert resp.status_code == 200
    first = await _collect_sse(resp)
    assert [e["type"] for e in first] == ["tts_chunk", "tts_done"]
    assert stub.calls == 1

    class _Bomb:
        async def health_check(self):
            return True

        async def stream_speech(self, **kw):
            raise AssertionError("synthesis must not be called on cache hit")
            yield b""  # pragma: no cover

    monkeypatch.setattr(tts_mod, "get_voice_engine", lambda cfg: _Bomb())
    resp = await fn(_req({"text": "こんにちは"}))
    assert resp.status_code == 200
    events = await _collect_sse(resp)
    assert [e["type"] for e in events] == ["tts_chunk", "tts_done"]
    assert events[0]["seq"] == 0
    assert base64.b64decode(events[0]["audio_base64"]) == blob
    assert events[1]["audio_url"].startswith("/api/tts/herta/cache/")


async def test_stream_miss_relays_and_caches(monkeypatch, tmp_path):
    b1 = _wav_blob(b"\x01\x02" * 800)
    b2 = _wav_blob(b"\x03\x04" * 800)
    stub = _StubEngine([b1, b2])
    _fake_ctx(monkeypatch, tmp_path, stub)
    fn = _routes()[("/api/tts/{persona}/stream", ("POST",))]
    resp = await fn(_req({"text": "さようなら"}))
    assert resp.status_code == 200
    events = await _collect_sse(resp)
    assert [e["type"] for e in events] == ["tts_chunk", "tts_chunk", "tts_done"]
    assert base64.b64decode(events[0]["audio_base64"]) == b1
    assert base64.b64decode(events[1]["audio_base64"]) == b2
    assert events[0]["seq"] == 0 and events[1]["seq"] == 1
    # 全文キーでcacheファイルが書かれる
    cache_dir = tmp_path / "persona" / "herta" / "tts_cache"
    wavs = list(cache_dir.glob("*.wav"))
    assert len(wavs) == 1
    assert events[2]["audio_url"].endswith(wavs[0].name)


async def test_stream_mid_error_writes_no_cache(monkeypatch, tmp_path):
    b1 = _wav_blob(b"\x01\x02" * 800)
    _fake_ctx(monkeypatch, tmp_path, _FailingEngine([b1]))
    fn = _routes()[("/api/tts/{persona}/stream", ("POST",))]
    resp = await fn(_req({"text": "えらー"}))
    assert resp.status_code == 200
    events = await _collect_sse(resp)
    assert [e["type"] for e in events] == ["tts_chunk", "tts_error"]
    assert base64.b64decode(events[0]["audio_base64"]) == b1
    cache_dir = tmp_path / "persona" / "herta" / "tts_cache"
    assert not list(cache_dir.glob("*.wav"))


class _RecordingEngine(_StubEngine):
    def __init__(self, blobs):
        super().__init__(blobs)
        self.seen = {}

    async def stream_speech(self, **kw):
        self.seen.update(kw)
        async for b in super().stream_speech(**kw):
            yield b


async def test_stream_uses_body_override_caption(monkeypatch, tmp_path):
    # oracle #1: bodyのemotion/caption overrideはstreamでもsynthesizeと同一に効く。
    blob = _wav_blob(b"\x01\x02" * 800)
    engine = _RecordingEngine([blob])
    _fake_ctx(monkeypatch, tmp_path, engine)
    fn = _routes()[("/api/tts/{persona}/stream", ("POST",))]
    resp = await fn(_req({"text": "こんにちは", "emotion": "joy", "caption": "オーバーライド字幕。"}))
    assert resp.status_code == 200
    events = await _collect_sse(resp)
    assert [e["type"] for e in events] == ["tts_chunk", "tts_done"]
    assert engine.seen["emotion"] == "joy"
    assert engine.seen["caption"] == "オーバーライド字幕。"


async def test_stream_ignores_parallel_caption_in_non_llm_mode(monkeypatch, tmp_path):
    # oracle #2: 非llmモードでは並列字幕タスク（llm由来）を採用しない。
    import asyncio

    from nous.api.http.routers.tts import CaptionResult, CaptionSnapshot, build_style_anchor

    blob = _wav_blob(b"\x01\x02" * 800)
    engine = _RecordingEngine([blob])
    state = types.SimpleNamespace(emotion="joy", emotion_intensity=0.8, appearance=None, relationship_status=None)

    async def _parallel():
        return CaptionResult("joy", "LLM磨きキャプション。", CaptionSnapshot("joy", 0.8))

    task = asyncio.create_task(_parallel())
    _fake_ctx(monkeypatch, tmp_path, engine, mode="anchor", state=state, task=task)
    try:
        fn = _routes()[("/api/tts/{persona}/stream", ("POST",))]
        resp = await fn(_req({"text": "こんにちは"}))
        assert resp.status_code == 200
        events = await _collect_sse(resp)
        assert [e["type"] for e in events] == ["tts_chunk", "tts_done"]
        assert engine.seen["caption"] == build_style_anchor("joy", 0.8)
        assert engine.seen["caption"] != "LLM磨きキャプション。"
    finally:
        await task
