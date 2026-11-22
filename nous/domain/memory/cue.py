"""Time cues for ``agent:task`` — deadline tags matched by the sweep.

``schedule_task`` writes a reservation as a memory tagged with an absolute
deadline::

    cue:time:2026-09-20T09:00    deadline (absolute ISO-8601)

The tag doubles as an index entry: ``get_by_tags`` pulls candidates and
``due_agent_tasks`` (schedule.py) matches deadlines here, so the write side and
the read side cannot drift apart. Firing semantics (due window, overdue grace)
are defined by the constants below.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nous.domain.memory.entities import Memory

CUE_TIME_PREFIX = "cue:time:"
# Fire once the deadline is inside this window — and keep firing while overdue
# (up to the grace below), because a missed reservation is exactly what an
# agent should notice.
DUE_WINDOW_HOURS = 24.0
OVERDUE_GRACE_HOURS = 72.0


def time_cue_tag(deadline: datetime) -> str:
    """Tag for an absolute deadline.

    seconds まで残す。minutes に丸めると最大 59 秒早く発火する（kanban #88）。
    読み手は ``parse_deadline`` なので、分精度の既存タグもそのまま読める。
    """
    return f"{CUE_TIME_PREFIX}{deadline.isoformat(timespec='seconds')}"


def parse_deadline(value: Any) -> datetime | None:
    """Parse a deadline from LLM output (ISO-8601 date or datetime). None on junk."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    # Date-only cues anchor at 09:00 local so "tomorrow" is not "in 5 minutes".
    if len(text) <= 10:
        parsed = parsed.replace(hour=9, minute=0)
    return parsed


def parse_time_cues(memory: Memory) -> list[datetime]:
    """All parseable deadlines cued on *memory*."""
    cues: list[datetime] = []
    for tag in getattr(memory, "tags", None) or []:
        if not tag.startswith(CUE_TIME_PREFIX):
            continue
        deadline = parse_deadline(tag[len(CUE_TIME_PREFIX) :])
        if deadline is not None:
            cues.append(deadline)
    return cues


def comparable(dt: datetime, now: datetime) -> datetime:
    """Make *dt* comparable with *now*.

    Deadline tags carry no timezone, while `get_now()` is tz-aware — mixing them
    raises `TypeError` on subtraction. Naive values are read in the caller's
    reference frame, which is what they were written in.

    `replace` and not `astimezone`: the latter reads a naive value in the
    *system* zone (UTC in the container), which silently shifts every "9am"
    deadline by 9 hours. Same convention as `time_utils.format_iso`.
    """
    if (dt.tzinfo is None) == (now.tzinfo is None):
        return dt
    if now.tzinfo is None:
        return dt.replace(tzinfo=None)
    return dt.replace(tzinfo=now.tzinfo)


def within_window(deadline: datetime, now: datetime, window_hours: float = DUE_WINDOW_HOURS) -> bool:
    """True when *deadline* is inside the due window (or overdue within grace)."""
    offset_hours = (comparable(deadline, now) - now).total_seconds() / 3600.0
    return -OVERDUE_GRACE_HOURS <= offset_hours <= window_hours


__all__ = [
    "CUE_TIME_PREFIX",
    "DUE_WINDOW_HOURS",
    "OVERDUE_GRACE_HOURS",
    "comparable",
    "parse_deadline",
    "parse_time_cues",
    "time_cue_tag",
    "within_window",
]
