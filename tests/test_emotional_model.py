"""
psychology.emotional_model.EmotionalModel のユニットテスト。

各テストは独立した一時 DB を使用する。
"""

import os
import tempfile

import pytest

import sys
sys.path.insert(0, "D:/VSCode/Nous")

from psychology.emotional_model import EmotionalModel, EmotionalState, EVENT_EMOTION_MAP


def _make_model(persona: str = "test") -> EmotionalModel:
    tmp = tempfile.mkdtemp()
    db_path = os.path.join(tmp, persona, "psychology.db")
    return EmotionalModel(persona, db_path)


# ── 正常系 ────────────────────────────────────────────────────────────────────

def test_initial_state_is_neutral():
    model = _make_model()
    assert model.state.surface_emotion == "neutral"
    assert model.state.mood == "calm"


def test_update_with_interesting_discovery_changes_emotion():
    model = _make_model()
    state = model.update("interesting_discovery", event_intensity=1.0)
    assert state.surface_emotion == "curiosity"
    assert state.surface_intensity > 0.0


def test_update_with_goal_achieved_positive_valence():
    model = _make_model()
    state = model.update("goal_achieved", event_intensity=1.0)
    assert state.mood_valence > 0.0


def test_update_with_boring_input_negative_valence():
    model = _make_model()
    state = model.update("boring_input", event_intensity=1.0)
    # boring_input は valence が負なので、初期値 0.0 より下がる
    assert state.mood_valence < 0.0


def test_mood_valence_clamped_within_range():
    model = _make_model()
    # 極端なイベントを繰り返しても -1.0〜1.0 に収まる
    for _ in range(20):
        model.update("goal_achieved", event_intensity=1.0)
    assert -1.0 <= model.state.mood_valence <= 1.0


def test_mood_arousal_clamped_within_range():
    model = _make_model()
    for _ in range(20):
        model.update("interesting_discovery", event_intensity=1.0)
    assert 0.0 <= model.state.mood_arousal <= 1.0


def test_get_display_emotion_returns_surface_when_intense():
    model = _make_model()
    model.update("interesting_discovery", event_intensity=1.0)
    # surface_intensity > 0.3 のとき surface_emotion が返る
    display = model.get_display_emotion()
    assert display == model.state.surface_emotion


def test_get_display_emotion_returns_mood_when_not_intense():
    model = _make_model()
    # intensity=0 なら surface_intensity=0 → mood が返る
    model.update("interesting_discovery", event_intensity=0.0)
    display = model.get_display_emotion()
    assert display == model.state.mood


def test_save_and_load_persists_state():
    tmp = tempfile.mkdtemp()
    db_path = os.path.join(tmp, "test_persist", "psychology.db")
    m1 = EmotionalModel("test_persist", db_path)
    m1.update("positive_interaction", event_intensity=1.0)
    saved_valence = m1.state.mood_valence

    # 同じ DB パスで再ロード
    m2 = EmotionalModel("test_persist", db_path)
    assert m2.state.mood_valence == pytest.approx(saved_valence)


# ── 異常系・境界値 ────────────────────────────────────────────────────────────

def test_update_with_unknown_event_uses_default():
    model = _make_model()
    state = model.update("unknown_event_type", event_intensity=1.0)
    assert state.surface_emotion == EVENT_EMOTION_MAP["default"]["emotion"]


def test_update_with_zero_intensity_minimal_change():
    model = _make_model()
    original_valence = model.state.mood_valence
    model.update("goal_achieved", event_intensity=0.0)
    # intensity=0 なら変化量は 0 * (1 - inertia) = 0 → valence は変化しない
    assert model.state.mood_valence == pytest.approx(
        original_valence * model.state.emotional_inertia
    )


def test_valence_arousal_to_mood_labels():
    model = _make_model()
    assert model._valence_arousal_to_mood(0.5, 0.5) == "excited"
    assert model._valence_arousal_to_mood(0.5, 0.2) == "content"
    assert model._valence_arousal_to_mood(-0.5, 0.5) == "anxious"
    assert model._valence_arousal_to_mood(-0.5, 0.2) == "sad"
    assert model._valence_arousal_to_mood(0.0, 0.3) == "calm"
