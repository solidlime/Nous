"""get_context 出力予算の強制（audit C3）。

P0 実測（docs/reviews/2026-09-19-parity-baseline.md §2）では、節ごとに全文を
出していたため最悪 1,231 tok（3,078 字）と docstring の ~500-800 tok 主張を
大きく上回っていた。ここでは `_format_lightweight_response` を直接駆動し、
節ごとの件数+文字数上限（_MAX_* 定数）と合計上限 _MAX_TOTAL_CHARS が
実際に強制されることを固定する。上限値は定数を import して参照し、
数値を二重管理しない。
"""

from __future__ import annotations

from datetime import UTC, datetime

from nous.api.mcp._tools_helpers import (
    _MAX_COMMITMENT_CHARS,
    _MAX_COMMITMENTS,
    _MAX_INSIGHT_CHARS,
    _MAX_INSIGHTS,
    _MAX_PROJECT_CHARS,
    _MAX_PROJECT_MEMORIES,
    _MAX_SUMMARIES,
    _MAX_SUMMARY_CHARS,
    _MAX_TOTAL_CHARS,
    _format_lightweight_response,
)
from nous.domain.memory.entities import Memory
from nous.domain.persona.entities import PersonaState


def _mem(key: str, content: str, tags: list[str] | None = None, importance: float = 0.5) -> Memory:
    now = datetime.now(UTC)
    return Memory(
        key=key,
        content=content,
        created_at=now,
        updated_at=now,
        importance=importance,
        tags=tags or [],
    )


def _state() -> PersonaState:
    return PersonaState(persona="tester", emotion="neutral", emotion_intensity=0.0)


def _render(
    *,
    goals: list[Memory] | None = None,
    top_memories: list[Memory] | None = None,
    reflections: list[Memory] | None = None,
    mental_models: list[Memory] | None = None,
    session_summaries: list[Memory] | None = None,
    project_memories: list[Memory] | None = None,
    recent: list[Memory] | None = None,
) -> str:
    return _format_lightweight_response(
        _state(),
        top_memories or [],
        goals or [],
        {},
        recent or [],
        reflections=reflections or [],
        mental_models=mental_models or [],
        session_summaries=session_summaries or [],
        project_memories=project_memories,
        project_name="demo" if project_memories else None,
    )


_SECTION_HEADERS = [
    "⚠️ YOUR ACTIVE COMMITMENTS:",
    "--- Your Recent Memories ---",
    "## YOUR ESSENTIAL STORY",
    "--- Recent Insights ---",
    "--- Behavior Patterns ---",
    "--- Recent Summaries ---",
    "--- PROJECT MEMORIES",
]


def _section_lines(text: str, header: str) -> list[str]:
    """header から次の節見出しまでの行を返す（切詰めマーカー行は除外）。"""
    start = text.find(header)
    if start == -1:
        return []
    rest = text[start + len(header) :]
    next_idx = len(rest)
    for other in _SECTION_HEADERS:
        if other == header:
            continue
        idx = rest.find(other)
        if idx != -1:
            next_idx = min(next_idx, idx)
    body = rest[:next_idx]
    return [row for row in body.splitlines() if row.strip() and not row.startswith("…")]


def _max_run(text: str, ch: str) -> int:
    """text 内で ch が連続する最大長（切詰め後の本文長の実測に使う）。"""
    best = 0
    run = 0
    for c in text:
        if c == ch:
            run += 1
            best = max(best, run)
        else:
            run = 0
    return best


def test_empty_case_stays_under_total_budget():
    text = _render()
    assert len(text) <= _MAX_TOTAL_CHARS
    # trailer は常に保持される
    assert "Use memory_search()" in text


def test_commitments_capped_by_count_and_chars():
    goals = [_mem(f"g{i}", "い" * 600, tags=["goal", "active"]) for i in range(50)]
    text = _render(goals=goals)

    lines = [row for row in _section_lines(text, "⚠️ YOUR ACTIVE COMMITMENTS:") if "🎯" in row]
    assert len(lines) <= _MAX_COMMITMENTS
    assert "い" * 600 not in text
    assert _max_run(text, "い") <= _MAX_COMMITMENT_CHARS


def test_insights_capped_by_count_and_chars():
    reflections = [_mem(f"r{i}", "あ" * 600, tags=["reflection"]) for i in range(10)]
    text = _render(reflections=reflections)

    lines = [row for row in _section_lines(text, "--- Recent Insights ---") if row.startswith("💡 ")]
    assert len(lines) <= _MAX_INSIGHTS
    assert "あ" * 600 not in text
    assert _max_run(text, "あ") <= _MAX_INSIGHT_CHARS


def test_summaries_capped_by_count_and_chars():
    summaries = [_mem(f"s{i}", "う" * 600, tags=["session_summary"]) for i in range(10)]
    text = _render(session_summaries=summaries)

    lines = [row for row in _section_lines(text, "--- Recent Summaries ---") if row.startswith("📝 ")]
    assert len(lines) <= _MAX_SUMMARIES
    assert "う" * 600 not in text
    assert _max_run(text, "う") <= _MAX_SUMMARY_CHARS


def test_project_memories_capped_by_count_and_chars():
    project = [_mem(f"p{i}", "え" * 600, tags=["project:demo"]) for i in range(20)]
    text = _render(project_memories=project)

    lines = [row for row in _section_lines(text, "--- PROJECT MEMORIES") if row.startswith("- ")]
    assert len(lines) <= _MAX_PROJECT_MEMORIES
    assert "え" * 600 not in text
    assert _max_run(text, "え") <= _MAX_PROJECT_CHARS
    # 既存表記を踏襲した切詰めマーカーが残る
    assert "full via memory_read" in text


def test_extreme_case_stays_under_total_budget():
    """全節を満杯にしても合計上限 _MAX_TOTAL_CHARS を越えない。"""
    goals = [_mem(f"g{i}", "い" * 600, tags=["goal", "active"]) for i in range(50)]
    reflections = [_mem(f"r{i}", "あ" * 600, tags=["reflection"]) for i in range(10)]
    summaries = [_mem(f"s{i}", "う" * 600, tags=["session_summary"]) for i in range(10)]
    project = [_mem(f"p{i}", "え" * 600, tags=["project:demo"]) for i in range(20)]
    top_memories = [_mem(f"t{i}", "お" * 600, tags=["reflection"], importance=0.9) for i in range(8)]
    recent = [_mem(f"rec{i}", "か" * 600) for i in range(5)]

    text = _render(
        goals=goals,
        reflections=reflections,
        session_summaries=summaries,
        project_memories=project,
        top_memories=top_memories,
        recent=recent,
    )

    assert len(text) <= _MAX_TOTAL_CHARS
    # 各節の上限は個別テストで固定済み。ここでは件数だけ総当たりで確認する。
    assert len([row for row in _section_lines(text, "⚠️ YOUR ACTIVE COMMITMENTS:") if "🎯" in row]) <= _MAX_COMMITMENTS
    assert (
        len([row for row in _section_lines(text, "--- Recent Insights ---") if row.startswith("💡 ")]) <= _MAX_INSIGHTS
    )
    assert (
        len([row for row in _section_lines(text, "--- Recent Summaries ---") if row.startswith("📝 ")])
        <= _MAX_SUMMARIES
    )
    assert (
        len([row for row in _section_lines(text, "--- PROJECT MEMORIES") if row.startswith("- ")])
        <= _MAX_PROJECT_MEMORIES
    )
