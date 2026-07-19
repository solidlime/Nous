"""Tests for _tools_helpers.py — one_shot_context formatting & state injection removal."""

from __future__ import annotations

from nous.domain.persona.entities import PersonaState


def _make_state(**kwargs) -> PersonaState:
    defaults = dict(persona="test_persona")
    defaults.update(kwargs)
    return PersonaState(**defaults)


def test_format_lightweight_includes_one_shot_context():
    """one_shot_context がフォーマット出力に含まれる"""
    from nous.api.mcp._tools_helpers import _format_lightweight_response

    state = _make_state()
    result = _format_lightweight_response(
        state,
        top_memories=[],
        goals=[],
        equipment={},
        recent=[],
        one_shot_context={"🗣️ 口調": "ツンデレ口調"},
    )
    assert "ツンデレ口調" in result
    assert "前回セッションからの状態" in result


def test_format_state_block_no_physical_mental_speech():
    """_format_state_block に physical_state / mental_state / speech が含まれない"""
    from nous.api.mcp._tools_helpers import _format_state_block

    state = _make_state(physical_state="疲れた", mental_state="集中")
    result = _format_state_block(state)
    assert "Physical:" not in result
    assert "Mental:" not in result
    assert "Speech:" not in result


def test_format_lightweight_no_physical_mental_state_parts():
    """state_parts に Body: / Mind: が含まれない"""
    from nous.api.mcp._tools_helpers import _format_lightweight_response

    state = _make_state(physical_state="疲れた", mental_state="集中")
    result = _format_lightweight_response(state, top_memories=[], goals=[], equipment={}, recent=[])
    assert "Body: 疲れた" not in result
    assert "Mind: 集中" not in result


def test_format_body_metrics_default_labels():
    """デフォルトの英語ラベルでbody metricsをフォーマット"""
    from nous.api.mcp._tools_helpers import _format_body_metrics

    state = _make_state(fatigue=0.4, warmth=0.74, arousal=0.59, heart_rate=0.69, pain=0.16)
    result = _format_body_metrics(state)
    assert "fatigue:40%" in result
    assert "warmth:74%" in result
    assert "arousal:59%" in result
    assert "heart:69%" in result
    assert "pain:16%" in result


def test_format_body_metrics_japanese_labels():
    """日本語ラベルでbody metricsをフォーマット"""
    from nous.api.mcp._tools_helpers import _format_body_metrics

    state = _make_state(fatigue=0.4, warmth=0.74)
    jp_labels = {"fatigue": "疲労", "warmth": "体温", "arousal": "覚醒", "heart_rate": "心拍", "pain": "痛み"}
    result = _format_body_metrics(state, labels=jp_labels)
    assert "疲労:40%" in result
    assert "体温:74%" in result


def test_format_body_metrics_partial_state():
    """一部のメトリクスだけ設定されている場合"""
    from nous.api.mcp._tools_helpers import _format_body_metrics

    state = _make_state(fatigue=0.5)
    result = _format_body_metrics(state)
    assert "fatigue:50%" in result
    assert "warmth" not in result  # Noneはスキップ


def test_format_body_metrics_empty_state():
    """すべてのメトリクスがNoneの場合、空文字を返す"""
    from nous.api.mcp._tools_helpers import _format_body_metrics

    state = _make_state()
    result = _format_body_metrics(state)
    assert result == ""


def test_format_state_block_uses_format_body_metrics():
    """_format_state_blockが_format_body_metricsを内部で使用していることを確認"""
    from nous.api.mcp._tools_helpers import _format_state_block

    state = _make_state(fatigue=0.4, warmth=0.74)
    result = _format_state_block(state)
    assert "fatigue:40%" in result
    assert "warmth:74%" in result
