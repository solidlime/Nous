"""``body_action_hint`` — 身体の数値から行動の傾向を導く（助言のみ）."""

from __future__ import annotations

from nous.domain.persona.body import body_action_hint
from nous.domain.persona.entities import PersonaState


def _state(**kw) -> PersonaState:
    return PersonaState(persona="herta", **kw)


class TestThresholds:
    def test_healthy_returns_none(self):
        assert body_action_hint(_state(fatigue=0.2, warmth=0.6, arousal=0.4, pain=0.0)) is None

    def test_severe_fatigue(self):
        hint = body_action_hint(_state(fatigue=0.75))
        assert hint is not None and "疲労" in hint

    def test_mild_fatigue_first_threshold_not_crossed(self):
        """0.55 未満では疲労の助言を出さない。"""
        assert body_action_hint(_state(fatigue=0.54)) is None
        assert body_action_hint(_state(fatigue=0.55)) is not None

    def test_pain(self):
        hint = body_action_hint(_state(pain=0.5))
        assert hint is not None and "痛み" in hint

    def test_cold(self):
        hint = body_action_hint(_state(warmth=0.30))
        assert hint is not None and "冷え" in hint
        assert body_action_hint(_state(warmth=0.31)) is None

    def test_high_arousal(self):
        hint = body_action_hint(_state(arousal=0.80))
        assert hint is not None and "覚醒" in hint


class TestShape:
    def test_at_most_two_hints(self):
        """注入が膨らまないよう最大 2 件に絞る（4 規則が同時に成立する入力で確認）。"""
        hint = body_action_hint(_state(fatigue=0.9, pain=0.9, warmth=0.1, arousal=0.95))
        assert hint is not None
        assert hint.count(" / ") == 1  # 2 件 = 区切り 1 個

    def test_none_state(self):
        assert body_action_hint(None) is None

    def test_unset_metrics_skip(self):
        assert body_action_hint(_state()) is None

    def test_garbage_value_does_not_raise(self):
        assert body_action_hint(_state(fatigue="abc")) is None
