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

def test_directive_guards_bad_input():
    assert build_caption_emotion_directive("", 0.9) == ""
    assert "nan%" not in build_caption_emotion_directive("joy", float("nan"))
    assert "500%" not in build_caption_emotion_directive("joy", 5.0)

def test_bucket_nan_never_persists():
    b = _emotion_bucket(float("nan"))
    assert b == 0.0
    assert b == b
