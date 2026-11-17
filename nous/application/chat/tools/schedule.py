"""schedule_task — エージェントが自分で決めた予定を記憶に置く（kanban #36）。

新しいテーブルは作らない。既存の ``cue:time:`` タグ機構
（``nous/domain/memory/cue.py``）に乗せるので、``ProspectiveWorker`` の照合と
``get_context`` の ⏰ 表示がそのまま効く。

タグ::

    agent:task                 予定そのもの（実行し終わったら外す）
    cue:time:<iso>             期限（cue.py と同形式・分精度）
    cue:recur:daily|weekly     繰り返し（実行後に期限を次回へ入れ直す）
    agent:task:fail:<n>        失敗回数（``FAIL_LIMIT`` で諦める）

実行側は ``nous/application/workers/prospective_worker.py``。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from nous.domain.memory.cue import (
    CUE_TIME_PREFIX,
    parse_deadline,
    parse_time_cues,
    time_cue_tag,
    within_window,
)
from nous.domain.shared.time_utils import get_now
from nous.infrastructure.logging.structured import get_logger

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from nous.application.use_cases import AppContext
    from nous.domain.config.chat_config import ChatConfig
    from nous.domain.memory.entities import Memory

logger = get_logger(__name__)

AGENT_TASK_TAG = "agent:task"
FAIL_TAG_PREFIX = "agent:task:fail:"
RECUR_TAG_PREFIX = "cue:recur:"
RECURS = ("daily", "weekly")
#: 何回失敗したら諦めるか（タグを外し ``agent.task.failed`` を残す）。
FAIL_LIMIT = 3

_WHEN_UNITS = {"m": 60.0, "h": 3600.0, "d": 86400.0}


def parse_when(value: object, now: datetime | None = None) -> datetime | None:
    """``2026-11-18T09:00`` / ``+2h`` / ``+30m`` / ``+3d`` → datetime。解釈できなければ None。

    相対表記の下限は 1 単位（``+0h`` は過去を作らないので弾く）。
    """
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if not text.startswith("+"):
        return parse_deadline(text)
    unit = text[-1].lower()
    if unit not in _WHEN_UNITS:
        return None
    try:
        amount = float(text[1:-1])
    except ValueError:
        return None
    if amount <= 0:
        return None
    return (now or get_now()) + timedelta(seconds=amount * _WHEN_UNITS[unit])


def recur_tag(recur: str) -> str:
    return f"{RECUR_TAG_PREFIX}{recur}"


def recur_of(memory: Memory) -> str | None:
    """``cue:recur:`` タグの値（daily/weekly 以外は None）。"""
    for tag in getattr(memory, "tags", None) or []:
        if tag.startswith(RECUR_TAG_PREFIX):
            value = str(tag[len(RECUR_TAG_PREFIX) :])
            if value in RECURS:
                return value
    return None


def fail_count(memory: Memory) -> int:
    counts = [
        int(tag[len(FAIL_TAG_PREFIX) :])
        for tag in (getattr(memory, "tags", None) or [])
        if tag.startswith(FAIL_TAG_PREFIX) and tag[len(FAIL_TAG_PREFIX) :].isdigit()
    ]
    return max(counts, default=0)


def due_agent_tasks(memories: Iterable[Memory], now: datetime | None = None) -> list[Memory]:
    """期限が来た ``agent:task``（未来は含めない・過期は grace 内のみ）。

    ``window_hours=0`` が要点: 通常の ``due_cues`` は「これから24時間」も拾うため、
    daily の次回（+24h）が同じ周期で再点火してしまう。
    """
    now = now or get_now()
    return [
        m
        for m in memories
        if AGENT_TASK_TAG in (getattr(m, "tags", None) or [])
        and any(within_window(d, now, window_hours=0.0) for d in parse_time_cues(m))
    ]


def _comparable(dt: datetime, ref: datetime) -> datetime:
    """cue タグは naive・``get_now()`` は aware なので、比較前に枠を揃える。"""
    if (dt.tzinfo is None) == (ref.tzinfo is None):
        return dt
    return dt.replace(tzinfo=None) if ref.tzinfo is None else dt.astimezone(ref.tzinfo)


def next_due(deadline: datetime, recur: str, now: datetime | None = None) -> datetime:
    """次回期限。停止中に溜まった分は1回で追いつく（何周も回さない）。"""
    step = timedelta(days=1 if recur == "daily" else 7)
    now = now or get_now()
    nxt = deadline + step
    while _comparable(nxt, now) <= now:
        nxt += step
    return nxt


def task_tags(tags: Sequence[str]) -> list[str]:
    """予定管理タグ（agent:task* / cue:time / cue:recur）を落とした残り。"""
    return [
        tag
        for tag in tags
        if not (tag.startswith(AGENT_TASK_TAG) or tag.startswith(CUE_TIME_PREFIX) or tag.startswith(RECUR_TAG_PREFIX))
    ]


def retry_tags(memory: Memory, fails: int) -> list[str]:
    """失敗して再挑戦する時のタグ（cue は残す＝次の巡回でまた拾える）。"""
    cues = [
        tag
        for tag in (getattr(memory, "tags", None) or [])
        if tag.startswith(CUE_TIME_PREFIX) or tag.startswith(RECUR_TAG_PREFIX)
    ]
    return [AGENT_TASK_TAG, *cues, f"{FAIL_TAG_PREFIX}{fails}"]


def done_tags(memory: Memory, recur: str | None, now: datetime | None = None) -> list[str]:
    """走らせ終わった後のタグ（recur なら次回の cue:time を入れ直す）。"""
    base = task_tags(getattr(memory, "tags", None) or [])
    if not recur:
        return base
    now = now or get_now()
    last = max(parse_time_cues(memory), default=now)
    return [*base, AGENT_TASK_TAG, time_cue_tag(next_due(last, recur, now)), recur_tag(recur)]


async def schedule_task(
    ctx: AppContext,
    when: str,
    prompt: str,
    recur: str | None = None,
    now: datetime | None = None,
) -> dict:
    """予定を記憶に1件作る。戻り値は builtin ツール共通の ``{status, message}``。"""
    text = " ".join(str(prompt or "").split())
    if not text:
        return {"status": "error", "message": "prompt は必須"}
    due = parse_when(when, now)
    if due is None:
        return {"status": "error", "message": f"when を解釈できない（ISO か +2h 形式）: {when!r}"}
    if recur and recur not in RECURS:
        return {"status": "error", "message": f"recur は {'/'.join(RECURS)} のどれか: {recur!r}"}

    tags = [AGENT_TASK_TAG, time_cue_tag(due), *([recur_tag(recur)] if recur else [])]
    result = await ctx.memory_service.create_memory(
        content=text,
        importance=0.7,
        tags=tags,
        emotion="neutral",
        # 同じ文面の予定を別時刻に置けるようにする（recur は特に同一内容）
        skip_duplicate_check=True,
    )
    if not getattr(result, "is_ok", False):
        return {"status": "error", "message": f"memory_create failed: {getattr(result, 'error', None)}"}

    iso = due.isoformat(timespec="minutes")
    logger.info("schedule_task: persona=%s due=%s recur=%s", getattr(ctx, "persona", "?"), iso, recur)
    return {"status": "ok", "message": f"予定を登録した: {text} @ {iso}", "due": iso}


async def handle_schedule_task(ctx: AppContext, config: ChatConfig | None, tool_input: dict) -> dict:
    """``builtin._BUILTIN_DISPATCH`` 用のハンドラ（``config`` は使わない）。"""
    recur = tool_input.get("recur")
    return await schedule_task(
        ctx,
        str(tool_input.get("when") or ""),
        str(tool_input.get("prompt") or ""),
        str(recur) if recur else None,
    )


async def run_self_turn(ctx: AppContext, prompt: str) -> None:
    """``session_id="self:<date>`` で1ターン走らせる。失敗は例外で呼び出し側へ。"""
    from nous.application.chat.service import ChatService

    config = ctx.config
    if config is None:
        raise RuntimeError("chat config が無い（AppContext.config is None）")
    session_id = f"self:{get_now().strftime('%Y-%m-%d')}"
    async for _ in ChatService().chat(ctx, config, session_id, prompt):
        pass
