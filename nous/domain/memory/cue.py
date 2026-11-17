"""Prospective-memory cues — audit M2 (v4.0).

A goal or a promise is only worth storing if the *present situation* brings it
back (Einstein & McDaniel 1990: prospective memory needs a cue — a time or an
event). Before v4.0 commitments were merely listed at ``get_context`` time, so
a promise due in an hour was never raised on its own.

Cue storage: **tags**. ``get_by_tags`` is already indexed, so a cue costs no
schema change and no migration::

    cue:time:2026-09-20T09:00    deadline (absolute ISO-8601)
    cue:event:健康診断            trigger entity (person / place / thing / event)

Matching lives here so the write side (memory extractor) and the read side
(``get_context`` / the hourly sweep) cannot drift apart.

``allow_overdue`` は呼び口ごとに違う（共通の照合器、別の問い）:
``get_context`` = True（期限切れも概観に出す）、自動注入（context_loader）
と毎時 sweep = False（過期を毎ターン押し付けない・変わった時だけ記録）。
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from nous.domain.shared.time_utils import get_now

if TYPE_CHECKING:
    from collections.abc import Iterable

    from nous.domain.memory.entities import Memory

CUE_TIME_PREFIX = "cue:time:"
CUE_EVENT_PREFIX = "cue:event:"
# Fire once the deadline is inside this window — and keep firing while overdue
# (up to the grace below), because a missed commitment is exactly what an
# agent should notice.
DUE_WINDOW_HOURS = 24.0
OVERDUE_GRACE_HOURS = 72.0

# 期限付きの約束はこの組でタグ付けする。書き手（memory_extractor）と
# 読み手（session_notes / context_loader）が同じ定数を見る。
PROMISE_TAGS: tuple[str, ...] = ("goal", "active", "interpersonal", "promise")


def time_cue_tag(deadline: datetime) -> str:
    """Tag for an absolute deadline."""
    return f"{CUE_TIME_PREFIX}{deadline.isoformat(timespec='minutes')}"


def event_cue_tag(entity: str) -> str:
    """Tag for an entity that should trigger recall."""
    return f"{CUE_EVENT_PREFIX}{entity.strip().lower()}"


def cue_tags(cue_time: Any = None, cue_event: Any = None) -> list[str]:
    """Build cue tags from LLM-supplied fields. Junk is dropped, never raised.

    Relative phrasings are the LLM's job to resolve against ``{current_time}``;
    anything unparseable here is simply ignored.
    """
    tags: list[str] = []
    deadline = parse_deadline(cue_time)
    if deadline is not None:
        tags.append(time_cue_tag(deadline))
    if isinstance(cue_event, str) and cue_event.strip():
        tags.append(event_cue_tag(cue_event))
    return tags


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


def event_cues(memory: Memory) -> list[str]:
    """All trigger entities cued on *memory* (lower-cased)."""
    return [
        tag[len(CUE_EVENT_PREFIX) :]
        for tag in (getattr(memory, "tags", None) or [])
        if tag.startswith(CUE_EVENT_PREFIX) and tag[len(CUE_EVENT_PREFIX) :]
    ]


def _comparable(dt: datetime, now: datetime) -> datetime:
    """Make *dt* comparable with *now*.

    Deadline tags carry no timezone, while ``get_now()`` is tz-aware — mixing them
    raises ``TypeError`` on subtraction. Naive values are read in the caller's
    reference frame, which is what they were written in.
    """
    if (dt.tzinfo is None) == (now.tzinfo is None):
        return dt
    if now.tzinfo is None:
        return dt.replace(tzinfo=None)
    return dt.astimezone(now.tzinfo)


def due_label(deadline: datetime, now: datetime) -> str:
    """Short human label: ``in 3h`` / ``2h overdue``."""
    hours = (_comparable(deadline, now) - now).total_seconds() / 3600.0
    if hours >= 0:
        return f"in {hours:.0f}h" if hours >= 1 else f"in {hours * 60:.0f}m"
    overdue = -hours
    return f"{overdue:.0f}h overdue" if overdue >= 1 else f"{overdue * 60:.0f}m overdue"


def due_cues(
    memories: Iterable[Memory],
    now: datetime | None = None,
    window_hours: float = DUE_WINDOW_HOURS,
    allow_overdue: bool = True,
) -> list[tuple[Memory, str]]:
    """Memories whose deadline is inside the window (or overdue within grace).

    ``allow_overdue=False`` keeps only upcoming deadlines — callers that inject
    upcoming commitments (get_context, the hourly sweep) must not restate an
    expired one; expiry is surfaced by the goal list instead.

    Returns ``[(memory, label), ...]`` sorted by deadline, earliest first.
    """
    if now is None:
        now = get_now()
    lower = -OVERDUE_GRACE_HOURS if allow_overdue else 0.0
    due: list[tuple[Memory, datetime]] = []
    for memory in memories:
        for deadline in parse_time_cues(memory):
            offset_hours = (_comparable(deadline, now) - now).total_seconds() / 3600.0
            if lower <= offset_hours <= window_hours:
                due.append((memory, deadline))
                break
    due.sort(key=lambda pair: pair[1])
    return [(memory, due_label(deadline, now)) for memory, deadline in due]


def event_cued_memories(memories: Iterable[Memory], text: str) -> list[Memory]:
    """Memories whose event cue appears in *text* (the current turn/context).

    This is the event-based half of prospective memory: seeing the entity is
    what triggers the commitment, not a clock.
    """
    if not text:
        return []
    haystack = text.lower()
    return [m for m in memories if any(entity in haystack for entity in event_cues(m))]


def within_window(deadline: datetime, now: datetime, window_hours: float = DUE_WINDOW_HOURS) -> bool:
    """True when *deadline* is inside the due window (or overdue within grace)."""
    offset_hours = (_comparable(deadline, now) - now).total_seconds() / 3600.0
    return -OVERDUE_GRACE_HOURS <= offset_hours <= window_hours


__all__ = [
    "CUE_EVENT_PREFIX",
    "CUE_TIME_PREFIX",
    "DUE_WINDOW_HOURS",
    "OVERDUE_GRACE_HOURS",
    "cue_tags",
    "due_cues",
    "due_label",
    "event_cue_tag",
    "event_cued_memories",
    "event_cues",
    "parse_deadline",
    "parse_time_cues",
    "time_cue_tag",
    "within_window",
]
