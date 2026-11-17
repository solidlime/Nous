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


class TestEmotionHintConfig:
    """#39: 閾値・文言の設定差し替えと不正設定のフォールバック。"""

    def test_custom_bands_move_boundaries(self):
        # 0.45 は既定では中間帯（>=0.35）。bands=(0.5, 0.8) では弱い帯。
        assert emotion_hint(_state("joy", 0.45), bands=(0.5, 0.8)) == emotion_hint(_state("joy", 0.1))
        # 0.75 は既定では強い帯（>0.7）。bands=(0.5, 0.8) では中間帯。
        assert emotion_hint(_state("joy", 0.75), bands=(0.5, 0.8)) != emotion_hint(_state("joy", 0.9))
        # 境界の内側は変わらない
        assert emotion_hint(_state("joy", 0.55), bands=(0.5, 0.8)) == emotion_hint(_state("joy", 0.55))

    def test_custom_texts_per_label(self):
        texts = {"joy": ["A", "B", "C"]}
        assert emotion_hint(_state("joy", 0.1), texts=texts) == "A"
        assert emotion_hint(_state("joy", 0.5), texts=texts) == "B"
        assert emotion_hint(_state("joy", 0.9), texts=texts) == "C"

    def test_unspecified_label_keeps_default(self):
        texts = {"joy": ["A", "B", "C"]}
        assert emotion_hint(_state("sadness", 0.9), texts=texts) == emotion_hint(_state("sadness", 0.9))

    def test_texts_key_is_normalized(self):
        assert emotion_hint(_state("嬉しい", 0.9), texts={"joy": ["A", "B", "C"]}) == "C"

    def test_inverted_bands_fall_back(self):
        assert emotion_hint(_state("joy", 0.45), bands=(0.8, 0.5)) == emotion_hint(_state("joy", 0.45))

    def test_short_text_list_falls_back(self):
        assert emotion_hint(_state("joy", 0.9), texts={"joy": ["A", "B"]}) == emotion_hint(_state("joy", 0.9))

    def test_non_str_element_falls_back(self):
        texts = {"joy": ["A", "B", 1]}
        assert emotion_hint(_state("joy", 0.9), texts=texts) == emotion_hint(_state("joy", 0.9))

    def test_newline_in_text_is_flattened(self):
        hint = emotion_hint(_state("joy", 0.9), texts={"joy": ["A", "B", "C\nD\te"]})
        assert "\n" not in hint
        assert hint == "C D e"

    def test_text_is_truncated_to_200(self):
        hint = emotion_hint(_state("joy", 0.9), texts={"joy": ["A", "B", "あ" * 201]})
        assert hint == "あ" * 200

    def test_dict_state_matches_namespace(self):
        raw = {"emotion": "joy", "emotion_intensity": 0.9}
        assert emotion_hint(raw) == emotion_hint(_state("joy", 0.9))

    def test_unknown_label_in_config_is_ignored(self):
        # normalize_emotion は未知ラベルを neutral に落とす。タイポで neutral 帯を
        # 乗っ取らないこと（neutral の既定文言のまま）。
        texts = {"zzz-typo": ["A", "B", "C"]}
        assert emotion_hint(_state("neutral", 0.9), texts=texts) == emotion_hint(_state("neutral", 0.9))
        assert emotion_hint(_state("joy", 0.9), texts=texts) == emotion_hint(_state("joy", 0.9))


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
        # #39 の if-then は prompt.py（system prompt 直下）へ移した。ここは強度ラベルと場所ヒントのみ。
        assert "感情: joy（強い）" in result
        assert emotion_hint(_make_state()) not in result
        assert place_hint("ラウンジ", DEFAULT_PLACES) in result

    async def test_injection_stays_short(self):
        from nous.application.chat.pipeline.prepare import _build_context_section

        result = await _build_context_section(_make_ctx(), _make_state())
        added = result.split("【現在の状態】\n", 1)[1].split("\n\n", 1)[0]
        assert len(added) < 300

    async def test_intensity_label_uses_configured_bands(self):
        """強度ラベルは if-then と同じ帯（設定値）を使うこと。"""
        from nous.application.chat.pipeline.aliveness import emotion_band
        from nous.application.chat.pipeline.prepare import _build_context_section

        state = _make_state()
        state.emotion = "anger"
        state.emotion_intensity = 0.5
        bands = (0.2, 0.4)  # 既定 (0.35, 0.7) と動かした設定帯
        result = await _build_context_section(_make_ctx(), state, emotion_bands=bands)
        # if-then 側が使う帯は band 2（強い）
        assert emotion_band(0.5, bands) == 2
        assert "感情: anger（強い）" in result

    async def test_trend_label_follows_configured_bands(self):
        """t1 と t3（感情の流れ）が同じ設定帯で同じラベルを出すこと。"""
        from datetime import timedelta

        from nous.application.chat.pipeline.prepare import _build_context_section
        from nous.domain.persona.entities import EmotionRecord
        from nous.domain.shared.time_utils import get_now

        def _rec(hours_ago: float) -> EmotionRecord:
            return EmotionRecord(
                emotion="sadness",
                intensity=0.3,
                timestamp=get_now() - timedelta(hours=hours_ago),
                context="失くした物の話",
            )

        ctx = _make_ctx()
        ctx.persona_service.get_emotion_history.return_value = Success([_rec(3.0), _rec(1.0)])
        state = _make_state()
        state.emotion = "anger"
        state.emotion_intensity = 0.5
        bands = (0.2, 0.4)  # 既定 (0.35, 0.7) では 0.5 は中間帯
        result = await _build_context_section(ctx, state, emotion_bands=bands)
        assert "感情: anger（強い）" in result
        assert "いまは anger（強い）が続いている。" in result

    async def test_reversed_bands_fall_back_for_both_labels(self):
        """逆転した設定帯でも t1 と trend が同じ既定帯に戻ること（無言の mismatch を防ぐ）。"""
        from datetime import timedelta

        from nous.application.chat.pipeline.prepare import _build_context_section
        from nous.domain.persona.entities import EmotionRecord
        from nous.domain.shared.time_utils import get_now

        def _rec(hours_ago: float) -> EmotionRecord:
            return EmotionRecord(
                emotion="sadness",
                intensity=0.3,
                timestamp=get_now() - timedelta(hours=hours_ago),
                context="失くした物の話",
            )

        ctx = _make_ctx()
        ctx.persona_service.get_emotion_history.return_value = Success([_rec(3.0), _rec(1.0)])
        state = _make_state()
        state.emotion = "anger"
        state.emotion_intensity = 0.5
        result = await _build_context_section(ctx, state, emotion_bands=(0.7, 0.2))
        # 既定帯 (0.35, 0.7) で 0.5 は中間帯
        assert "感情: anger（やや強い）" in result
        assert "いまは anger（やや強い）が続いている。" in result
