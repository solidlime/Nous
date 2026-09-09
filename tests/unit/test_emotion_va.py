"""Tests for emotion_to_va (valence-arousal mapping, Phase 0 spike)."""

from __future__ import annotations

from nous.domain.value_objects import _EMOTION_KEYWORD_MAP, emotion_to_va


def test_covers_all_canonical_labels():
    """Every canonical emotion label must have a V-A entry."""
    for label in _EMOTION_KEYWORD_MAP:
        v, a = emotion_to_va(label)
        assert -1.0 <= v <= 1.0
        assert -1.0 <= a <= 1.0


def test_known_values():
    assert emotion_to_va("joy") == (0.9, 0.4)
    assert emotion_to_va("anger") == (-0.6, 0.8)
    assert emotion_to_va("neutral") == (0.0, 0.0)
    assert emotion_to_va("sadness") == (-0.7, -0.4)


def test_unknown_returns_zero():
    assert emotion_to_va("grief") == (0.0, 0.0)
    assert emotion_to_va("") == (0.0, 0.0)
