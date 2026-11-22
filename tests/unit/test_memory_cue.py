"""Time-cue primitive tests (agent:task scheduling support).

cue.py の time-cue 機構（parse_deadline / parse_time_cues / within_window /
comparable）は schedule_task（agent:task）の deadline 判定が依存する。
約束照合（due_cues / event cues）は削除済み — ここでは primitive のみ検証する。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from nous.domain.memory.cue import (
    CUE_TIME_PREFIX,
    DUE_WINDOW_HOURS,
    OVERDUE_GRACE_HOURS,
    parse_deadline,
    parse_time_cues,
    time_cue_tag,
    within_window,
)
from nous.domain.memory.entities import Memory


def _mem(key: str, content: str = "予定", tags: list[str] | None = None, **kwargs) -> Memory:
    now = datetime(2026, 9, 19, 12, 0)
    return Memory(
        key=key,
        content=content,
        created_at=now,
        updated_at=now,
        importance=0.8,
        tags=tags or [],
        **kwargs,
    )


class TestParseDeadline:
    def test_date_only_anchors_at_morning(self):
        parsed = parse_deadline("2026-09-20")
        assert parsed == datetime(2026, 9, 20, 9, 0)

    def test_parse_deadline_rejects_garbage(self):
        assert parse_deadline("明日") is None
        assert parse_deadline("") is None
        assert parse_deadline(None) is None


class TestTimeCueTag:
    def test_tag_uses_seconds_precision(self):
        deadline = datetime(2026, 9, 20, 9, 0)
        # 秒切り捨てると +30m の予定が最大 59 秒早く発火するので seconds 精度で持つ（kanban #88）。
        assert time_cue_tag(deadline) == f"{CUE_TIME_PREFIX}2026-09-20T09:00:00"


class TestParseTimeCues:
    def test_parse_time_cues_ignores_junk_tag(self):
        mem = _mem("m1", tags=[f"{CUE_TIME_PREFIX}garbage", "project"])
        assert parse_time_cues(mem) == []

    def test_parses_tagged_deadline(self):
        mem = _mem("m1", tags=[time_cue_tag(datetime(2026, 9, 20, 9, 0))])
        assert parse_time_cues(mem) == [datetime(2026, 9, 20, 9, 0)]


class TestWithinWindow:
    def test_within_window_boundaries(self):
        now = datetime(2026, 9, 19, 12, 0)
        assert within_window(now + timedelta(hours=DUE_WINDOW_HOURS), now) is True
        assert within_window(now + timedelta(hours=DUE_WINDOW_HOURS + 0.1), now) is False
        assert within_window(now - timedelta(hours=OVERDUE_GRACE_HOURS), now) is True

    def test_within_window_accepts_mixed_frames(self):
        """naive タグと aware タグの混在（#84）。"""
        now = datetime(2026, 9, 19, 12, 0, tzinfo=ZoneInfo("Asia/Tokyo"))
        assert within_window(datetime(2026, 9, 19, 15, 0), now) is True
        assert within_window(datetime(2026, 9, 20, 13, 0), now) is False
