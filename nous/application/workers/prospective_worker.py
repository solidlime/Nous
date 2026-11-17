"""ProspectiveWorker — 期限の近い約束を 1 時間ごとに照合する（audit M2）。

注入そのものは ``get_context`` が行う（``context_loader`` の「いま思い出すべき
約束」）。この worker はその周期的な半分で、同じ照合器 ``due_cues`` を毎時
回し、期限入りのコミットメントを ``prospective.due`` の session event として
残す。push 経路も持たない（Nous に自発通知のチャネルはまだ無い）。

記憶は原則書かない（get_context がライブ計算するので行を増やす意味がない）。
例外は ``agent:task``（kanban #36）: 期限が来たら自分で1ターン走らせ、
走らせた後にタグを外す（recur は次回を入れ直す）。

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
    recur_of,
    retry_tags,
    run_self_turn,
)
from nous.domain.memory.cue import due_cues
from nous.domain.shared.time_utils import get_now
from nous.infrastructure.logging.structured import get_logger

if TYPE_CHECKING:
    from nous.application.use_cases import AppContext
    from nous.domain.memory.entities import Memory

logger = get_logger(__name__)

# shortcut: fixed interval, move to Settings if a tuning knob is needed.
DEFAULT_INTERVAL_SECONDS = 3600
EVENT_TYPE = "prospective.due"
TASK_DONE_EVENT = "agent.task.ran"
TASK_FAILED_EVENT = "agent.task.failed"
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
        while not self._stop_event.wait(self.interval):
            try:
                self.run_cycle()
            except Exception:
                logger.exception("ProspectiveWorker cycle failed")

    def run_cycle(self) -> None:
        """1 サイクル（手動運転・検証用に public）。"""
        from nous.application.use_cases import AppContextRegistry

        for persona in list(AppContextRegistry.personas()):
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

        for persona in list(AppContextRegistry.personas()):
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
                await run_self_turn(ctx, f"{SELF_TURN_PREFIX}{task.content}")
            except Exception as e:
                self._fail(ctx, persona, task, e)
                continue
            self._finish(ctx, persona, task)

    def _finish(self, ctx: AppContext, persona: str, task: Memory) -> None:
        recur = recur_of(task)
        tags = done_tags(task, recur)
        ctx.memory_service.update_memory(task.key, tags=tags)
        self._event(ctx, persona, TASK_DONE_EVENT, f"{task.content[:80]} (recur={recur or '-'})")

    def _fail(self, ctx: AppContext, persona: str, task: Memory, error: Exception) -> None:
        fails = fail_count(task) + 1
        give_up = fails >= FAIL_LIMIT
        tags = done_tags(task, None) if give_up else retry_tags(task, fails)
        ctx.memory_service.update_memory(task.key, tags=tags)
        summary = f"{task.content[:60]} ({fails}/{FAIL_LIMIT}) {type(error).__name__}: {error}"
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
