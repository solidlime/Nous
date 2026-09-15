"""Tests for _tools_helpers.py — one_shot_context formatting & state injection removal."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

from nous.domain.memory.entities import Memory
from nous.domain.persona.entities import PersonaState

# 相対時刻 "(3mo ago)" 相当のパターン
_REL_TIME_RE = re.compile(r"\(\d+(?:m|h|d|mo|y) ago\)")


def _make_state(**kwargs) -> PersonaState:
    defaults = dict(persona="test_persona")
    defaults.update(kwargs)
    return PersonaState(**defaults)


def _timed_mem(key: str, content: str, created_days_ago: float) -> Memory:
    """created_at を now から遡らせて作る Memory（テスト決定性のため固定の bucket に落ちる差を使う）。"""
    now = datetime.now(UTC)
    created = now - timedelta(days=created_days_ago)
    return Memory(
        key=key,
        content=content,
        created_at=created,
        updated_at=created,
        importance=0.8,
        tags=["tag"],
    )


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


def _block(text: str, header: str, next_header: str) -> str:
    """セクション header から next_header までのブロックを切り出す。"""
    start = text.index(header)
    end = text.index(next_header, start + len(header))
    return text[start:end]


def test_lightweight_sections_carry_created_at_relative_time():
    """Essential Story / Recent Insights / Recent Summaries の各行に relative time が付く。"""
    from nous.api.mcp._tools_helpers import _format_lightweight_response

    state = _make_state()
    top_memories = [_timed_mem("t1", "essential story memory", created_days_ago=366)]
    reflections = [_timed_mem("r1", "reflection insight", created_days_ago=100)]
    mental_models = [_timed_mem("p1", "behavior pattern", created_days_ago=366)]
    session_summaries = [_timed_mem("s1", "session summary", created_days_ago=100)]

    result = _format_lightweight_response(
        state,
        top_memories=top_memories,
        goals=[],
        equipment={},
        recent=[],
        reflections=reflections,
        mental_models=mental_models,
        session_summaries=session_summaries,
    )

    essential = _block(result, "## YOUR ESSENTIAL STORY", "\n--- Recent Insights")
    assert _REL_TIME_RE.search(essential), f"Essential Story に時刻なし: {essential}"
    assert "essential story memory" in essential

    insights = _block(result, "--- Recent Insights", "\n--- Behavior Patterns")
    assert _REL_TIME_RE.search(insights), f"Recent Insights に時刻なし: {insights}"
    assert "reflection insight" in insights

    summaries = _block(result, "--- Recent Summaries", "💡 Use memory_search")
    assert _REL_TIME_RE.search(summaries), f"Recent Summaries に時刻なし: {summaries}"
    assert "session summary" in summaries


def test_behavior_patterns_carry_no_relative_time():
    """Behavior Patterns は集約概念のため、relative time を付けない。"""
    from nous.api.mcp._tools_helpers import _format_lightweight_response

    state = _make_state()
    mental_models = [
        _timed_mem("p1", "pattern one", created_days_ago=366),
        _timed_mem("p2", "pattern two", created_days_ago=1),
    ]
    result = _format_lightweight_response(
        state,
        top_memories=[_timed_mem("t1", "story", created_days_ago=366)],
        goals=[],
        equipment={},
        recent=[],
        mental_models=mental_models,
    )

    patterns = _block(result, "--- Behavior Patterns", "💡 Use memory_search")
    assert "pattern one" in patterns and "pattern two" in patterns
    assert not _REL_TIME_RE.search(patterns), f"Behavior Patterns に時刻が付いた: {patterns}"
    assert "1y ago" not in patterns
