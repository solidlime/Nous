import pytest
pytestmark = pytest.mark.unit
from nous.api.http.routers.tts import build_style_anchor

def test_emotion_whitespace_normalizes():
    a = build_style_anchor("  ", 0.9)
    b = build_style_anchor("", 0.9)
    assert a == b
