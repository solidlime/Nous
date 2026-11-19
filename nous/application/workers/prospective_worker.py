"""ProspectiveWorker — 期限の近い約束を 1 時間ごとに照合する（audit M2）。

注入そのものは ``get_context`` が行う（``context_loader`` の「いま思い出すべき
約束」）。この worker はその周期的な半分で、同じ照合器 ``due_cues`` を毎時
回し、期限入りのコミットメントを ``prospective.due`` の session event として
残す。push 経路も持たない（Nous に自発通知のチャネルはまだ無い）。

記憶は原則書かない（get_context がライブ計算するので行を増やす意味がない）。
例外は ``agent:task``（kanban #36）: 期限が来たら自分で1ターン走らせ、
走らせた後にタグを外す（recur は次回を入れ直す）。

発火の精度（kanban #64/#68）:

- ``agent:task`` は ``_next_wait()`` が最短の未来期限まで眠るので、期限の
  30 秒以降（``MIN_WAIT_SECONDS``）に走る。未来の期限が1つも無い時だけ
  ``interval``（既定 1 時間・設定不可）で起きる。期限を過ぎたタスクは
  ``OVERDUE_GRACE_HOURS``(=72h) 内なら次の巡回で拾い直す。
- ``cue:time`` を持つ約束の照合（``prospective.due``）は毎時巡回なので、
  表示は最大 1 時間古い。イベント駆動ではない。

注意: 巡回対象は ``AppContextRegistry.personas()`` が持つ、すなわち
**一度でも HTTP/チャットでアクセスされた persona だけ**（AppContext は遅延生成）。
起動後に一度も触られない persona の期限はここでは拾わない。
"""

from __future__ import annotations

import asyncio
import threading
from typing import TYPE_CHECKING

from nous.application.chat.tools.schedule import (
    AGENT_TASK_TAG,
    FAIL_LIMIT,
    done_tags,
    due_agent_tasks,
    fail_count,
    next_task_wait_seconds,
    recur_of,
    retry_tags,
    run_self_turn,
)
from nous.application.workers.announce import speak_to_main
from nous.domain.memory.cue import due_cues
from nous.domain.shared.time_utils import get_now
from nous.infrastructure.logging.structured import get_logger

if TYPE_CHECKING:
    from nous.application.use_cases import AppContext
    from nous.domain.memory.entities import Memory

logger = get_logger(__name__)

# shortcut: fixed interval, move to Settings if a tuning knob is needed.
DEFAULT_INTERVAL_SECONDS = 3600
#: 期限ぴったりに起きるための下限（負荷と精度のトレードオフ）。
MIN_WAIT_SECONDS = 30.0
EVENT_TYPE = "prospective.due"
TASK_DONE_EVENT = "agent.task.ran"
TASK_FAILED_EVENT = "agent.task.failed"
TASK_SPOKE_EVENT = "agent.task.spoke"
SELF_TURN_PREFIX = "[自分で決めた予定] "


class ProspectiveWorker:
    """Hourly sweep over active goals/promises with a time cue."""

    def __init__(self, interval_seconds: int = DEFAULT_INTERVAL_SECONDS) -> None:
        self.interval = interval_seconds
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        #: persona → 直前に通知した約束キー（同じ約束を毎時積み直さない）。
        self._last_due: dict[str, frozenset[str]] = {}

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="prospective-worker")
        self._thread.start()
        logger.info("ProspectiveWorker started (interval=%ss)", self.interval)

    def stop(self, timeout: float = 5.0) -> None:
        self._stop_event.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=timeout)
        logger.info("ProspectiveWorker stopped")

    def _run(self) -> None:
        while not self._stop_event.is_set():
            self._stop_event.wait(self._next_wait())
            if self._stop_event.is_set():
                break
            try:
                self.run_cycle()
            except Exception:
                logger.exception("ProspectiveWorker cycle failed")

    def _next_wait(self) -> float:
        """次の ``agent:task`` 期限までの待ち秒数（kanban #64）。

        毎時固定だと 09:00 の予定が最大 60 分遅れるので、最短の期限まで眠る。
        期限が無い・計算できない時は従来の ``interval``。``MIN_WAIT`` で下限を敷く。
        """
        from nous.application.use_cases import AppContextRegistry

        now = get_now()
        waits: list[float] = []
        for persona in AppContextRegistry.all_personas():
            try:
                ctx = AppContextRegistry.get(persona)
                result = ctx.memory_service.get_by_tags([AGENT_TASK_TAG])
            except Exception:
                continue
            if not result.is_ok:
                continue
            wait = next_task_wait_seconds(getattr(result, "value", None) or [], now)
            if wait is not None:
                waits.append(wait)
        if not waits:
            return float(self.interval)
        return min(float(self.interval), max(MIN_WAIT_SECONDS, min(waits)))

    def run_cycle(self) -> None:
        """1 サイクル（手動運転・検証用に public）。"""
        from nous.application.use_cases import AppContextRegistry

        for persona in AppContextRegistry.all_personas():
            try:
                ctx = AppContextRegistry.get(persona)
                due = self._due(ctx)
            except Exception:
                # 削除中の PersonaNotFoundError もここで拾う（他ペルソナの周期を止めない）
                logger.exception("ProspectiveWorker: persona=%s failed", persona)
                continue
            keys = frozenset(m.key for m, _ in due)
            if not keys:
                self._last_due.pop(persona, None)
                continue
            if keys == self._last_due.get(persona):
                continue
            self._last_due[persona] = keys
            self._record(ctx, persona, due)

        self.run_agent_tasks()

    def run_agent_tasks(self) -> None:
        """期限が来た ``agent:task`` を全部拾って1ターンずつ走らせる（kanban #36）。

        ``run_cycle`` からもテストからも呼べるよう public。同期版はここで
        ``asyncio.run`` する（worker は素のスレッドでループを持たない）。
        """
        from nous.application.use_cases import AppContextRegistry

        for persona in AppContextRegistry.all_personas():
            try:
                ctx = AppContextRegistry.get(persona)
                result = ctx.memory_service.get_by_tags([AGENT_TASK_TAG])
                tasks = due_agent_tasks(getattr(result, "value", None) or []) if result.is_ok else []
                if not tasks:
                    continue
                asyncio.run(self._execute_tasks(ctx, persona, tasks))
            except Exception:
                logger.exception("ProspectiveWorker: agent task sweep failed persona=%s", persona)

    async def _execute_tasks(self, ctx: AppContext, persona: str, tasks: list[Memory]) -> None:
        for task in tasks:
            try:
                text = await run_self_turn(ctx, f"{SELF_TURN_PREFIX}{task.content}")
            except Exception as e:
                self._fail(ctx, persona, task, e)
                continue
            if text is None:
                # 他のターンが走っていて実行できなかった。タグは外さず次の巡回に回す
                # （kanban #69: 空文字を成功扱いにすると予定が痩せていく）。
                logger.info("ProspectiveWorker: skipped, turn busy persona=%s key=%s", persona, task.key)
                continue
            self._speak(ctx, text, f"task={task.key}")
            try:
                self._finish(ctx, persona, task)
            except Exception as e:  # 1件の後始末失敗でそのサイクルの残タスクを落とさない
                logger.warning("ProspectiveWorker: finish failed persona=%s", persona, exc_info=True)
                self._fail(ctx, persona, task, e)

    @staticmethod
    def _speak(ctx: AppContext, text: str, ref: str = "") -> None:
        """実行結果を main チャットへ届ける（kanban #65）。失敗しても実行自体は続ける。"""
        if not text.strip() or ctx.config is None:
            return
        try:
            speak_to_main(ctx, text.strip(), ctx.config.max_stored_messages, TASK_SPOKE_EVENT, ref)
        except Exception:
            logger.warning("ProspectiveWorker: speak failed persona=%s", ctx.persona, exc_info=True)

    def _rewrite_tags(self, ctx: AppContext, persona: str, task: Memory, tags: list[str], what: str) -> bool:
        """タグを書き換える。失敗を握り潰すと、同じタスクが毎サイクル再実行される (kanban #82 B1)。"""
        result = ctx.memory_service.update_memory(task.key, tags=tags)
        if result.is_ok:
            return True
        # Success には error が無いので getattr 経由で拾う（実行時は常に Failure）
        logger.warning(
            "ProspectiveWorker: %s failed to rewrite tags persona=%s key=%s: %s",
            what,
            persona,
            task.key,
            getattr(result, "error", None),
        )
        return False

    def _finish(self, ctx: AppContext, persona: str, task: Memory) -> None:
        recur = recur_of(task)
        tags = done_tags(task, recur)
        if not self._rewrite_tags(ctx, persona, task, tags, "finish"):
            # タグが消せないまま成功扱いにすると、次サイクルで同じ発言を繰り返す。
            raise RuntimeError(f"failed to clear task tags: {task.key}")
        self._event(ctx, persona, TASK_DONE_EVENT, f"task={task.key} {task.content[:80]} (recur={recur or '-'})")

    def _fail(self, ctx: AppContext, persona: str, task: Memory, error: Exception) -> None:
        fails = fail_count(task) + 1
        give_up = fails >= FAIL_LIMIT
        tags = done_tags(task, None) if give_up else retry_tags(task, fails)
        # 失敗カウンタが書けないと FAIL_LIMIT に永久に届かないので、少なくとも警告は残す。
        self._rewrite_tags(ctx, persona, task, tags, f"fail ({fails}/{FAIL_LIMIT})")
        summary = f"task={task.key} {task.content[:60]} ({fails}/{FAIL_LIMIT}) {type(error).__name__}: {error}"
        self._event(ctx, persona, TASK_FAILED_EVENT, summary)
        logger.warning("ProspectiveWorker: task failed persona=%s %s", persona, summary)

    @staticmethod
    def _event(ctx: AppContext, persona: str, event_type: str, summary: str) -> None:
        from nous.domain.memory.session_event import SessionEvent
        from nous.infrastructure.sqlite.session_event_repo import SessionEventRepository

        try:
            SessionEventRepository(ctx.connection).insert(
                SessionEvent(
                    session_id="prospective_worker",
                    persona=persona,
                    event_type=event_type,
                    timestamp=get_now(),
                    summary=summary[:200],
                )
            )
        except Exception:
            logger.debug("ProspectiveWorker: failed to record %s", event_type, exc_info=True)

    @staticmethod
    def _due(ctx: AppContext) -> list[tuple[Memory, str]]:
        result = ctx.memory_service.get_by_tags(["goal", "active"])
        if not getattr(result, "is_ok", False):
            return []
        return due_cues(getattr(result, "value", None) or [], get_now(), allow_overdue=False)

    @staticmethod
    def _record(ctx: AppContext, persona: str, due: list[tuple[Memory, str]]) -> None:
        from nous.domain.memory.session_event import SessionEvent
        from nous.infrastructure.sqlite.session_event_repo import SessionEventRepository

        summary = "近い約束: " + "; ".join(f"{m.content[:80]} ({label})" for m, label in due)
        logger.info("ProspectiveWorker: persona=%s %s", persona, summary)
        try:
            SessionEventRepository(ctx.connection).insert(
                SessionEvent(
                    session_id="prospective_worker",
                    persona=persona,
                    event_type=EVENT_TYPE,
                    timestamp=get_now(),
                    summary=summary[:200],
                )
            )
        except Exception:
            logger.debug("ProspectiveWorker: failed to record event", exc_info=True)
