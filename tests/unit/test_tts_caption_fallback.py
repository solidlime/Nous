import pytest
pytestmark = pytest.mark.unit
from nous.api.http.routers.tts import _resolve_emotion_mode, build_style_anchor

def test_emotion_whitespace_normalizes():
    a = build_style_anchor("  ", 0.9)
    b = build_style_anchor("", 0.9)
    assert a == b


class _ChatCfg:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def test_mode_explicit_passthrough():
    assert _resolve_emotion_mode(_ChatCfg(voice_emotion_mode="llm")) == "llm"
    assert _resolve_emotion_mode(_ChatCfg(voice_emotion_mode="off")) == "off"


def test_mode_derived_canonical_order():
    mk = lambda link, llm: _ChatCfg(
        voice_emotion_mode="", voice_emotion_link=link, irodori_caption_llm_enabled=llm
    )
    assert _resolve_emotion_mode(mk(True, True)) == "llm"
    assert _resolve_emotion_mode(mk(True, False)) == "anchor"
    assert _resolve_emotion_mode(mk(False, True)) == "off"
    assert _resolve_emotion_mode(mk(False, False)) == "off"
