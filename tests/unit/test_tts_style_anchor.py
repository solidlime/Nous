"""tests/unit/test_tts_style_anchor.py"""

import inspect

from nous.api.http.routers import tts as tts_mod
from nous.api.http.routers.tts import _emotion_bucket, build_style_anchor


def test_anchor_contains_consistency_suffix():
    a = build_style_anchor("joy", 0.8)
    assert "全体を通して一貫した" in a
    assert "明るく" in a


def test_anchor_low_intensity_softens():
    a = build_style_anchor("anger", 0.2)
    assert "抑えめ" in a or "穏やか" in a


def test_anchor_inner_nuance_preserved():
    # 内面系の未知感情はラベルを潰さず残す (違和感の効き対策)
    a = build_style_anchor("違和感", 0.6)
    assert "違和感" in a
    assert "全体を通して一貫した" in a


def test_anchor_empty_emotion_no_crash():
    a = build_style_anchor("", 0.0)
    assert isinstance(a, str) and "全体を通して一貫した" in a


def test_anchor_includes_baseline_when_given():
    a = build_style_anchor("neutral", 0.5, appearance="大人びた雰囲気", relationship="親しい相手")
    assert "親しい相手" in a or "大人びた" in a


def test_bucket_rounds_to_01():
    assert _emotion_bucket(0.82) == 0.8
    assert _emotion_bucket(0.86) == 0.9
    assert _emotion_bucket(0.0) == 0.0


def test_on_path_uses_low_temperature():
    src = inspect.getsource(tts_mod)
    assert "temperature=0.2" in src
    assert "max_tokens=128" in src


def test_on_system_forbids_text_driven_switch():
    src = inspect.getsource(tts_mod)
    assert "切替は禁止" in src
    assert "【固定条件】" in src
    assert "【参考本文" in src
