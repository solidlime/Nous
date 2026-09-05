import asyncio
import contextlib
import types

import pytest

pytestmark = pytest.mark.unit
from nous.api.http.routers import tts as tts_mod


def _chat_cfg(mode):
    return types.SimpleNamespace(
        voice_emotion_mode=mode,
        voice_emotion_link=True,
        irodori_caption_llm_enabled=(mode == "llm"),
        provider="x",
        model="m",
        api_key="",
        base_url="",
        irodori_caption_llm_model="",
    )


def _patch_config(monkeypatch, tmp_path, mode):
    import nous.domain.chat_config as chat_config_mod

    cfg = _chat_cfg(mode)
    monkeypatch.setattr(
        chat_config_mod, "ChatConfigFileRepository", lambda root: types.SimpleNamespace(get=lambda persona: cfg)
    )
    monkeypatch.setattr(
        "nous.config.settings.get_settings",
        lambda: types.SimpleNamespace(data_root=str(tmp_path)),
    )
    return cfg


def _benign_ctx():
    return types.SimpleNamespace(
        persona_service=types.SimpleNamespace(
            get_context=lambda persona: types.SimpleNamespace(is_ok=True, value=None)
        ),
    )


def _bomb_ctx():
    def _bomb(persona):
        raise AssertionError("persona state must not be consulted")

    return types.SimpleNamespace(
        persona_service=types.SimpleNamespace(get_context=_bomb),
    )


@pytest.fixture(autouse=True)
def _clean_caption_tasks():
    tts_mod._CAPTION_TASKS.clear()
    yield
    for t in list(tts_mod._CAPTION_TASKS.values()):
        if not t.done():
            t.cancel()
    tts_mod._CAPTION_TASKS.clear()


async def _cancel(task):
    if task is not None and not task.done():
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task


async def test_kickoff_skips_non_llm_modes(monkeypatch, tmp_path):
    _patch_config(monkeypatch, tmp_path, "off")
    tts_mod.kickoff_caption_task("herta", _bomb_ctx(), "こんにちは")
    await asyncio.sleep(0)
    assert tts_mod.take_caption_task("herta") is None


async def test_kickoff_starts_task_in_llm_mode(monkeypatch, tmp_path):
    _patch_config(monkeypatch, tmp_path, "llm")
    tts_mod.kickoff_caption_task("herta", _benign_ctx(), "こんにちは")
    task = tts_mod.take_caption_task("herta")
    assert task is not None
    await _cancel(task)
    # takeはpopする（2回目はNone）
    assert tts_mod.take_caption_task("herta") is None


async def test_kickoff_cancels_previous(monkeypatch, tmp_path):
    _patch_config(monkeypatch, tmp_path, "llm")
    ctx = _benign_ctx()
    tts_mod.kickoff_caption_task("herta", ctx, "1回目")
    first = tts_mod._CAPTION_TASKS.get("herta")
    assert first is not None
    tts_mod.kickoff_caption_task("herta", ctx, "2回目")
    second = tts_mod.take_caption_task("herta")
    assert second is not None
    assert second is not first
    await _cancel(first)
    await _cancel(second)
    assert tts_mod.take_caption_task("herta") is None


def test_chat_endpoint_hooks_kickoff():
    import inspect

    from nous.api.http.routers.chat import chat_stream as chat_stream_mod

    assert "kickoff_caption_task" in inspect.getsource(chat_stream_mod.chat_endpoint)
