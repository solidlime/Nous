import asyncio
import types

import pytest

pytestmark = pytest.mark.unit
from nous.api.http.routers.tts import CaptionResult, _resolve_caption


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


@pytest.fixture
def fake_chat_config_off():
    return _chat_cfg("off")


@pytest.fixture
def fake_chat_config_llm():
    return _chat_cfg("llm")


@pytest.fixture
def fake_ctx():
    def _bomb(persona):
        raise AssertionError("persona state must not be consulted")

    return types.SimpleNamespace(
        persona_service=types.SimpleNamespace(get_context=_bomb),
    )


def test_off_mode_returns_neutral_without_llm(fake_ctx, fake_chat_config_off):
    res = asyncio.run(_resolve_caption("herta", fake_ctx, fake_chat_config_off, ref_text="こんにちは"))
    assert isinstance(res, CaptionResult)
    assert res.emotion == "neutral"
    assert res.caption is None
    assert res.snapshot.emotion == "neutral"


def test_override_passthrough_skips_state(fake_ctx, fake_chat_config_llm):
    # use_override相当: state参照があっても呼ばれない（ FakeCtx.get_contextにbombを仕込む ）
    res = asyncio.run(
        _resolve_caption("herta", fake_ctx, fake_chat_config_llm,
                         ref_text="本文", override_emotion="joy", override_caption="明るく話す。")
    )
    assert res.emotion == "joy"
    assert res.caption == "明るく話す。"
