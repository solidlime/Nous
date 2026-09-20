"""Prospective-memory cue tests — audit M2 (v4.0).

A commitment needs a cue that brings it back: a deadline (time) or an entity
(event). These tests pin the storage format and the matching rules, because the
write side (extractor) and the read side (get_context / hourly sweep) both
depend on them agreeing.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from nous.domain.memory.cue import (
    CUE_EVENT_PREFIX,
    CUE_TIME_PREFIX,
    DUE_WINDOW_HOURS,
    OVERDUE_GRACE_HOURS,
    cue_tags,
    due_cues,
    due_label,
    event_cue_tag,
    event_cued_memories,
    parse_deadline,
    parse_time_cues,
    time_cue_tag,
    within_window,
)
from nous.domain.memory.entities import Memory


def _mem(key: str, content: str = "約束", tags: list[str] | None = None, **kwargs) -> Memory:
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


class TestCueTags:
    def test_time_and_event_tags(self):
        tags = cue_tags("2026-09-20T09:00", "健康診断")
        assert f"{CUE_TIME_PREFIX}2026-09-20T09:00" in tags
        # Entities are lower-cased so matching is case-insensitive
        assert event_cue_tag("健康診断") == f"{CUE_EVENT_PREFIX}健康診断"
        assert event_cue_tag("Kyoto Trip") == f"{CUE_EVENT_PREFIX}kyoto trip"

    def test_junk_is_dropped_not_raised(self):
        assert cue_tags(None, None) == []
        assert cue_tags("not-a-date", "") == []
        assert cue_tags(12345, 42) == []

    def test_date_only_anchors_at_morning(self):
        parsed = parse_deadline("2026-09-20")
        assert parsed == datetime(2026, 9, 20, 9, 0)

    def test_parse_deadline_rejects_garbage(self):
        assert parse_deadline("明日") is None
        assert parse_deadline("") is None
        assert parse_deadline(None) is None


class TestDueCues:
    def test_deadline_inside_window_fires(self):
        now = datetime(2026, 9, 19, 12, 0)
        deadline = now + timedelta(hours=3)
        mem = _mem("m1", "面接の約束", tags=[time_cue_tag(deadline)])
        due = due_cues([mem], now)
        assert len(due) == 1
        assert due[0][0].key == "m1"
        assert due[0][1] == "in 3h"

    def test_deadline_beyond_window_does_not_fire(self):
        now = datetime(2026, 9, 19, 12, 0)
        mem = _mem("m1", tags=[time_cue_tag(now + timedelta(hours=DUE_WINDOW_HOURS + 1))])
        assert due_cues([mem], now) == []

    def test_overdue_within_grace_still_fires(self):
        now = datetime(2026, 9, 19, 12, 0)
        mem = _mem("m1", tags=[time_cue_tag(now - timedelta(hours=2))])
        due = due_cues([mem], now)
        assert len(due) == 1
        assert "overdue" in due[0][1]

    def test_overdue_beyond_grace_is_dropped(self):
        now = datetime(2026, 9, 19, 12, 0)
        mem = _mem("m1", tags=[time_cue_tag(now - timedelta(hours=OVERDUE_GRACE_HOURS + 1))])
        assert due_cues([mem], now) == []

    def test_multiple_cues_yield_one_entry_sorted(self):
        now = datetime(2026, 9, 19, 12, 0)
        later = _mem("later", tags=[time_cue_tag(now + timedelta(hours=10))])
        sooner = _mem("sooner", tags=[time_cue_tag(now + timedelta(hours=1))])
        assert [m.key for m, _ in due_cues([later, sooner], now)] == ["sooner", "later"]

    def test_memory_without_cue_never_fires(self):
        now = datetime(2026, 9, 19, 12, 0)
        assert due_cues([_mem("m1", tags=["goal", "active"])], now) == []

    def test_parse_time_cues_ignores_junk_tag(self):
        mem = _mem("m1", tags=[f"{CUE_TIME_PREFIX}garbage", "goal"])
        assert parse_time_cues(mem) == []

    def test_within_window_boundaries(self):
        now = datetime(2026, 9, 19, 12, 0)
        assert within_window(now + timedelta(hours=DUE_WINDOW_HOURS), now) is True
        assert within_window(now + timedelta(hours=DUE_WINDOW_HOURS + 0.1), now) is False
        assert within_window(now - timedelta(hours=OVERDUE_GRACE_HOURS), now) is True

    def test_due_label_minutes(self):
        now = datetime(2026, 9, 19, 12, 0)
        assert due_label(now + timedelta(minutes=30), now) == "in 30m"
        assert due_label(now - timedelta(minutes=15), now) == "15m overdue"


class TestEventCues:
    def test_entity_in_text_fires(self):
        mem = _mem("m1", "健康診断の結果を聞く", tags=[event_cue_tag("健康診断")])
        assert [m.key for m in event_cued_memories([mem], "明日は健康診断だよ")] == ["m1"]

    def test_case_insensitive_match(self):
        mem = _mem("m1", tags=[event_cue_tag("Kyoto")])
        assert [m.key for m in event_cued_memories([mem], "I loved kyoto last year")] == ["m1"]

    def test_no_text_no_match(self):
        mem = _mem("m1", tags=[event_cue_tag("健康診断")])
        assert event_cued_memories([mem], "") == []

    def test_unrelated_text_no_match(self):
        mem = _mem("m1", tags=[event_cue_tag("健康診断")])
        assert event_cued_memories([mem], "今日はコードを書いた") == []
