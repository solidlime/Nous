"""tests/unit/test_aliveness.py — #39 感情の if-then / #42 場所ヒントのテスト。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from nous.application.chat.pipeline.aliveness import emotion_hint, place_hint
from nous.domain.persona.places import DEFAULT_PLACES
from nous.domain.shared.result import Success


def _state(emotion=None, intensity=0.5, environment=None):
    return SimpleNamespace(emotion=emotion, emotion_intensity=intensity, environment=environment)


class TestEmotionHint:
    """強度帯の境界 (<0.35 / 0.35–0.7 / >0.7) で別の1行を返すこと。"""

    def test_bands_split_at_boundaries(self):
        low = emotion_hint(_state("joy", 0.34))
        mid = emotion_hint(_state("joy", 0.35))
        high = emotion_hint(_state("joy", 0.71))
        assert low and mid and high
        assert len({low, mid, high}) == 3

    def test_upper_boundary_is_middle_band(self):
        assert emotion_hint(_state("joy", 0.7)) == emotion_hint(_state("joy", 0.6))

    def test_lower_boundary_is_middle_band(self):
        assert emotion_hint(_state("joy", 0.35)) == emotion_hint(_state("joy", 0.7))

    def test_unknown_label_falls_back_to_band(self):
        assert emotion_hint(_state("zzz-unknown", 0.9)) == emotion_hint(_state("neutral", 0.9))

    def test_japanese_label_is_normalized(self):
        assert emotion_hint(_state("嬉しい", 0.5)) == emotion_hint(_state("joy", 0.5))

    def test_missing_emotion_returns_empty(self):
        assert emotion_hint(_state(None)) == ""
        assert emotion_hint(None) == ""

    def test_bad_intensity_falls_back_to_middle(self):
        assert emotion_hint(_state("joy", "x")) == emotion_hint(_state("joy", None))

    def test_hint_is_one_line(self):
        for emotion in ("joy", "sadness", "anger", "anxiety"):
            for intensity in (0.1, 0.5, 0.9):
                assert "\n" not in emotion_hint(_state(emotion, intensity))


class TestPlaceHint:
    """カタログにある場所だけ1行返し、未知は空文字。"""

    def test_known_place(self):
        assert place_hint("ラウンジ", DEFAULT_PLACES).strip()

    def test_slug_resolves(self):
        assert place_hint("jishitsu", DEFAULT_PLACES) == place_hint("自室", DEFAULT_PLACES)

    def test_place_embedded_in_free_text(self):
        assert place_hint("自室。部屋も外も冷えている。", DEFAULT_PLACES) == place_hint("自室", DEFAULT_PLACES)

    def test_unknown_place_returns_empty(self):
        assert place_hint("見知らぬ倉庫", DEFAULT_PLACES) == ""
        assert place_hint("", DEFAULT_PLACES) == ""
        assert place_hint(None, DEFAULT_PLACES) == ""

    def test_every_catalog_place_has_hint(self):
        for place in DEFAULT_PLACES:
            assert place_hint(place.name, DEFAULT_PLACES).strip(), place.slug


def _make_ctx():
    ctx = MagicMock()
    ctx.persona = "test"
    ctx.memory_service = MagicMock()
    ctx.memory_service.get_by_tags.return_value = Success([])
    ctx.memory_service.get_top_by_importance.return_value = Success([])
    ctx.persona_service = MagicMock()
    ctx.persona_service.get_emotion_history.return_value = Success([])
    ctx.equipment_service = MagicMock()
    ctx.equipment_service.get_equipment.return_value = Success({})
    return ctx


def _make_state():
    state = MagicMock()
    state.emotion = "joy"
    state.emotion_intensity = 0.8
    state.environment = "ラウンジ"
    state.mental_state = None
    state.physical_state = None
    state.relationship_status = None
    state.user_info = {}
    state.persona_info = {}
    state.last_conversation_time = None
    state.fatigue = None
    state.pain = None
    state.arousal = None
    return state


class TestInjection:
    """状態ブロック直後に 1〜2 行だけ足されること。"""

    async def test_context_section_contains_hints(self):
        from nous.application.chat.pipeline.prepare import _build_context_section

        result = await _build_context_section(_make_ctx(), _make_state())
        assert emotion_hint(_make_state()) in result
        assert place_hint("ラウンジ", DEFAULT_PLACES) in result

    async def test_injection_stays_short(self):
        from nous.application.chat.pipeline.prepare import _build_context_section

        result = await _build_context_section(_make_ctx(), _make_state())
        added = result.split("【現在の状態】\n", 1)[1].split("\n\n", 1)[0]
        assert len(added) < 300
