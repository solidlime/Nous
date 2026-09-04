"""tests/unit/test_tts_emotion_caption.py"""

from nous.api.http.routers.tts import EMOTION_TONE_HINTS, build_caption_emotion_directive


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


def test_directive_sadness_anger_keys_are_live():
    """#081 指摘3: 正典ラベル sadness/anger でヒントが発火すること（死んだキー禁止）。"""
    assert "低く" in build_caption_emotion_directive("sadness", 0.8)
    assert "強く短く" in build_caption_emotion_directive("anger", 0.8)


def test_hint_keys_are_canonical_emotions():
    """EMOTION_TONE_HINTS のキーは VALID_EMOTIONS の部分集合でなければならない。"""
    from nous.domain.value_objects import VALID_EMOTIONS

    assert set(EMOTION_TONE_HINTS) <= set(VALID_EMOTIONS)


def test_directive_empty_emotion_returns_empty():
    """#081 指摘4: 感情が空なら指示文を生成しない（空疎文字列の LLM 混入防止）。"""
    assert build_caption_emotion_directive("", 0.5) == ""
