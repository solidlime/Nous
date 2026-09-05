import json
import types

import pytest

pytestmark = pytest.mark.unit
from nous.api.http.routers import tts as tts_mod
from nous.api.http.routers.tts import _resolve_tts_override


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

    return types.SimpleNamespace(path_params={"persona": "herta"}, headers={}, json=_json)


def _fake_ctx(monkeypatch, tmp_path, *, mode="llm", forbid_state=False):
    chat_cfg = types.SimpleNamespace(
        voice_model="",
        voice_url="",
        voice_speed=1.0,
        voice_emotion_mode=mode,
        voice_emotion_link=True,
        irodori_caption_llm_enabled=(mode == "llm"),
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
    import nous.domain.chat_config as chat_config_mod

    monkeypatch.setattr(
        chat_config_mod, "ChatConfigFileRepository", lambda root: types.SimpleNamespace(get=lambda persona: chat_cfg)
    )
    monkeypatch.setattr(
        "nous.config.settings.get_settings",
        lambda: types.SimpleNamespace(data_root=str(tmp_path)),
    )

    def _get_context(persona):
        if forbid_state:
            raise AssertionError("persona state must not be consulted for override")
        return types.SimpleNamespace(is_ok=True, value=None)

    fake_ctx = types.SimpleNamespace(
        settings=types.SimpleNamespace(
            irodori=types.SimpleNamespace(url="http://127.0.0.1:9", voice="v", model="m", timeout_seconds=5)
        ),
        persona_service=types.SimpleNamespace(get_context=_get_context),
    )
    monkeypatch.setattr(tts_mod, "_safe_get_context", lambda persona: fake_ctx)

    class _Engine:
        async def health_check(self):
            return True

        async def synthesize(self, **kw):
            return b"RIFF...."

    monkeypatch.setattr(tts_mod, "get_voice_engine", lambda cfg: _Engine())

    def _no_provider(*a, **k):
        raise AssertionError("LLM must not be consulted for override")

    monkeypatch.setattr("nous.infrastructure.llm.factory.get_provider", _no_provider)
    return chat_cfg


async def test_override_skips_llm_and_echoes_back(monkeypatch, tmp_path):
    # emotion-only override: state参照もLLM生成もせず、解決済みemotionをそのまま返す。
    _fake_ctx(monkeypatch, tmp_path, mode="llm", forbid_state=True)
    fn = _routes()[("/api/tts/{persona}", ("POST",))]
    resp = await fn(_req({"text": "こんにちは", "emotion": "joy"}))
    assert resp.status_code == 200
    data = json.loads(resp.body)
    assert data["emotion"] == "joy"
    assert data["caption"] is None


def test_resolve_override_emotion_only():
    assert _resolve_tts_override({"emotion": "joy"}) == ("joy", None, True)


def test_resolve_override_caption_only():
    assert _resolve_tts_override({"caption": "明るく"}) == ("neutral", "明るく", True)


def test_resolve_override_both_and_empty():
    assert _resolve_tts_override({"emotion": "joy", "caption": "明るく"}) == ("joy", "明るく", True)
    assert _resolve_tts_override({}) == ("neutral", None, False)
    assert _resolve_tts_override({"emotion": "  ", "caption": ["x"]}) == ("neutral", None, False)


def test_resolve_override_coerces_non_string():
    assert _resolve_tts_override({"emotion": 123}) == ("123", None, True)


def test_endpoints_share_override_and_mode_helpers():
    import inspect

    src = inspect.getsource(tts_mod.register_tts_routes)
    assert src.count("_resolve_tts_override(body)") == 2
    assert src.count("_resolve_emotion_mode(chat_config)") == 2


def test_override_cache_key_uses_resolved_values():
    from nous.api.http.routers.tts import _tts_cache_key

    k1 = _tts_cache_key(text="a", emotion="joy", caption="明るく", voice_speed=1.0, voice_override=None)
    k2 = _tts_cache_key(text="a", emotion="joy", caption="暗く", voice_speed=1.0, voice_override=None)
    assert k1 != k2
