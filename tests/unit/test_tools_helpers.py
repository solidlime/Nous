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


def test_format_lightweight_no_speech_style_injection():
    """speech_style が context_state 経由で注入されない"""
    from nous.api.mcp._tools_helpers import _format_lightweight_response

    state = _make_state(speech_style="丁寧")
    result = _format_lightweight_response(state, top_memories=[], goals=[], equipment={}, recent=[])
    # context_state の speech_style は注入されないはず
    assert "🗣️ REMEMBER" not in result


def test_format_state_block_no_physical_mental_speech():
    """_format_state_block に physical_state / mental_state / speech が含まれない"""
    from nous.api.mcp._tools_helpers import _format_state_block

    state = _make_state(physical_state="疲れた", mental_state="集中", speech_style="丁寧")
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
