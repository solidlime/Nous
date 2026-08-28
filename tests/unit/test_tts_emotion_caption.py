"""tests/unit/test_tts_emotion_caption.py"""

from nous.api.http.routers.tts import build_caption_emotion_directive


def test_directive_contains_emotion_and_tone():
    d = build_caption_emotion_directive("joy", 0.8)
    assert "joy" in d
    assert "明るく" in d  # joy のトーンヒント


def test_directive_unknown_emotion_falls_back():
    d = build_caption_emotion_directive("mysterious", 0.5)
    assert "mysterious" in d
    assert "感情" in d


def test_directive_low_intensity():
    d = build_caption_emotion_directive("joy", 0.1)
    assert "穏やか" in d  # 強度が低い場合は抑えめ指示
