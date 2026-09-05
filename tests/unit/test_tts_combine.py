import wave, io, math, struct
import json
import types
import pytest
pytestmark = pytest.mark.unit
from nous.api.http.routers import tts as tts_mod
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


def _combine_fn(monkeypatch, *, state=None):
    captured = {}

    class _MCP:
        def custom_route(self, path, methods):
            def deco(fn):
                captured[(path, tuple(methods))] = fn
                return fn

            return deco

    tts_mod.register_tts_routes(_MCP())

    def _get_context(persona):
        return types.SimpleNamespace(is_ok=True, value=state)

    fake_ctx = types.SimpleNamespace(
        settings=types.SimpleNamespace(
            irodori=types.SimpleNamespace(url="http://127.0.0.1:9", voice="v", model="m", timeout_seconds=5)
        ),
        persona_service=types.SimpleNamespace(get_context=_get_context),
    )
    monkeypatch.setattr(tts_mod, "_safe_get_context", lambda persona: fake_ctx)
    return captured[("/api/tts/{persona}/combine", ("POST",))]


def _req(body):
    async def _json():
        return body

    return types.SimpleNamespace(path_params={"persona": "herta"}, headers={}, json=_json)


def _chat_cfg(**over):
    d = dict(
        voice_model="",
        voice_url="",
        voice_speed=1.0,
        voice_emotion_mode="anchor",
        voice_emotion_link=True,
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
        irodori_chunk_min_chars=85,
        irodori_seed=0,
    )
    d.update(over)
    return types.SimpleNamespace(**d)


def _patch_tts_stack(monkeypatch, tmp_path, chat_cfg, get_context_fn):
    captured = {}

    class _MCP:
        def custom_route(self, path, methods):
            def deco(fn):
                captured[(path, tuple(methods))] = fn
                return fn

            return deco

    tts_mod.register_tts_routes(_MCP())
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
        persona_service=types.SimpleNamespace(get_context=get_context_fn),
    )
    monkeypatch.setattr(tts_mod, "_safe_get_context", lambda persona: fake_ctx)

    class _Engine:
        async def health_check(self):
            return True

        async def synthesize(self, **kw):
            return _sine_wav(1600)

    monkeypatch.setattr(tts_mod, "get_voice_engine", lambda cfg: _Engine())
    return captured


async def test_combine_non_string_fulltext_400(monkeypatch):
    fn = _combine_fn(monkeypatch)
    resp = await fn(_req({"files": ["a.wav"], "fullText": 123}))
    assert resp.status_code == 400


async def test_combine_non_list_files_400(monkeypatch):
    fn = _combine_fn(monkeypatch)
    resp = await fn(_req({"files": 123, "fullText": "hi"}))
    assert resp.status_code == 400


async def test_combine_key_matches_synthesize_key(monkeypatch, tmp_path):
    # anchor mode + 固定state: 全文POSTのキー == combineの全文キー（同一URL）。
    state = types.SimpleNamespace(emotion="joy", emotion_intensity=0.8, appearance=None, relationship_status=None)
    captured = _patch_tts_stack(
        monkeypatch,
        tmp_path,
        _chat_cfg(),
        lambda persona: types.SimpleNamespace(is_ok=True, value=state),
    )
    full = "結合テスト用の全文です。ほら、これが一致するはずだよ。"
    syn = captured[("/api/tts/{persona}", ("POST",))]
    r1 = await syn(_req({"text": full}))
    assert r1.status_code == 200
    url1 = json.loads(r1.body)["audio_url"]
    comb = captured[("/api/tts/{persona}/combine", ("POST",))]
    r2 = await comb(_req({"files": [url1.split("/")[-1]], "fullText": full}))
    assert r2.status_code == 200
    assert json.loads(r2.body)["audio_url"] == url1


async def test_combine_key_matches_synthesize_key_derived_off(monkeypatch, tmp_path):
    # link OFF + llm ON → off 導出: 明示mode無しでも両EPが同一mode/キーに解決する。
    from nous.api.http.routers.tts import _resolve_emotion_mode

    chat_cfg = _chat_cfg(voice_emotion_link=False, irodori_caption_llm_enabled=True)
    del chat_cfg.voice_emotion_mode
    assert _resolve_emotion_mode(chat_cfg) == "off"

    def _bomb(persona):
        raise AssertionError("state must not be consulted in off mode")

    captured = _patch_tts_stack(monkeypatch, tmp_path, chat_cfg, _bomb)
    full = "導出オフの一致テスト全文だよ。"
    r1 = await captured[("/api/tts/{persona}", ("POST",))](_req({"text": full}))
    assert r1.status_code == 200
    d1 = json.loads(r1.body)
    assert d1["emotion"] == "neutral" and d1["caption"] is None
    url1 = d1["audio_url"]
    r2 = await captured[("/api/tts/{persona}/combine", ("POST",))](
        _req({"files": [url1.split("/")[-1]], "fullText": full})
    )
    assert r2.status_code == 200
    assert json.loads(r2.body)["audio_url"] == url1

