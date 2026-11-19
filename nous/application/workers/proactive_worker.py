"""ProactiveWorker — 自分から声をかける push 経路（kanban #44）。

``ProspectiveWorker`` が「予定を走らせる」のに対し、こちらは **ユーザーへ
届ける** 側。一定時間話していない persona について LLM に 1 ターン回し、
「話すことがある」と判断された時だけ main 履歴 + SSE で本文を届ける。

判定は 3 段（すべて満たす時だけ判断に進む）:

1. ``session_config.proactive_enabled``
2. ``last_user_message_at`` から ``proactive_idle_minutes`` 以上経過
   （``chat.message`` / ``turn.completed``。``chat.llm_response`` を数えると
   自分の発言で idle がリセットされる自己ループになる）
3. ``proactive.spoke`` から ``proactive_cooldown_minutes`` 以上経過

判断用のターンは ``proactive:<date>`` セッションで走らせ、main の文脈を汚さない
（main には「話すと決めた本文」だけを assistant として追記する）。
応答が ``<silent>`` なら何も残さない。

注意: 巡回対象は ``AppContextRegistry.personas()``、すなわち **一度でも
HTTP/チャットでアクセスされた persona だけ**（AppContext は遅延生成）。
"""

from __future__ import annotations

import asyncio
import json
import threading
from typing import TYPE_CHECKING

from nous.application.chat.service import ChatService, get_turn_hub
from nous.application.workers.announce import SPOKE_EVENT, speak_to_main
from nous.domain.memory.session_ids import PROACTIVE_SESSION_PREFIX
from nous.domain.shared.time_utils import get_now
from nous.infrastructure.logging.structured import get_logger
from nous.infrastructure.sqlite.session_event_repo import SessionEventRepository

if TYPE_CHECKING:
    from datetime import datetime

    from nous.application.use_cases import AppContext

logger = get_logger(__name__)

DEFAULT_INTERVAL_SECONDS = 1800
SILENT_MARK = "<silent>"


def idle_minutes(ctx: AppContext, now: datetime, threshold_minutes: int) -> float | None:
    """最後のユーザー発話からの経過分数。``threshold_minutes`` 未満なら None。

    ``chat.message`` / ``turn.completed`` を数える（``chat.llm_response`` は自分の
    発言で idle がリセットされる自己ループになるため数えない）。一度も話して
    いない persona は None（相手が居ない）。
    """
    repo = SessionEventRepository(ctx.connection)
    last_user = repo.last_user_message_at(ctx.persona)
    if last_user is None:
        return None
    if last_user.tzinfo is None:  # sqlite に naive で入った古い行を現地時刻とみなす
        last_user = last_user.replace(tzinfo=now.tzinfo)
    idle = (now - last_user).total_seconds() / 60
    return idle if idle >= threshold_minutes else None


class ProactiveWorker:
    """Idle な persona に、話すことがある時だけ 1〜2 文を push する。"""

    def __init__(self, interval_seconds: int = DEFAULT_INTERVAL_SECONDS) -> None:
        self.interval = interval_seconds
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        #: persona → 直前に判断した時刻（``proactive_interval_minutes`` の間隔を空ける）。
        #: shortcut: tick は固定 30 分。設定が tick より短い間隔を望んでもそこまで詰まらない。
        self._last_check: dict[str, datetime] = {}
        #: persona → 話した時刻（イベント記録に失敗したときのクールダウン代替、kanban #82 B3）。
        self._spoke_at: dict[str, datetime] = {}

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="proactive-worker")
        self._thread.start()
        logger.info("ProactiveWorker started (interval=%ss)", self.interval)

    def stop(self, timeout: float = 5.0) -> None:
        self._stop_event.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=timeout)
        logger.info("ProactiveWorker stopped")

    def _run(self) -> None:
        while not self._stop_event.wait(self.interval):
            try:
                self.run_cycle()
            except Exception:
                logger.exception("ProactiveWorker cycle failed")

    def run_cycle(self) -> None:
        """1 サイクル（手動運転・検証用に public）。"""
        from nous.application.use_cases import AppContextRegistry

        for persona in AppContextRegistry.all_personas():
            try:
                ctx = AppContextRegistry.get(persona)
            except Exception:
                # 削除中の PersonaNotFoundError もここで拾う（他ペルソナを止めない）
                logger.exception("ProactiveWorker: persona=%s failed", persona)
                continue
            try:
                asyncio.run(self.run_persona(ctx))
            except Exception:
                logger.exception("ProactiveWorker: persona=%s turn failed", persona)

    async def run_persona(self, ctx: AppContext) -> str | None:
        """1 persona 分の判定。話したら本文、黙ったら None。"""
        config = ctx.config
        if config is None or not config.session_config.proactive_enabled:
            return None

        now = get_now()
        last_check = self._last_check.get(ctx.persona)
        if last_check is not None:
            if last_check.tzinfo is None:
                last_check = last_check.replace(tzinfo=now.tzinfo)
            interval = config.session_config.proactive_interval_minutes
            if (now - last_check).total_seconds() / 60 < interval:
                return None

        idle_minutes = self._idle_minutes(ctx, now)
        if idle_minutes is None:
            return None

        text = await self._deliberate(ctx, idle_minutes, now)
        if not text:
            # LLM 失敗・ターン衝突は「判断できなかった」ので間隔を進めない (kanban #82 B6)。
            return None
        self._last_check[ctx.persona] = now
        if SILENT_MARK in text:
            return None
        self._speak(ctx, text, config.max_stored_messages)
        return text

    def _idle_minutes(self, ctx: AppContext, now: datetime) -> float | None:
        """idle 分数。話す条件を満たさなければ None。"""
        session_config = ctx.config.session_config  # type: ignore[union-attr]
        idle = idle_minutes(ctx, now, session_config.proactive_idle_minutes)
        if idle is None:
            return None

        last_spoke = SessionEventRepository(ctx.connection).last_event_at(ctx.persona, SPOKE_EVENT)
        if last_spoke is not None and last_spoke.tzinfo is None:
            last_spoke = last_spoke.replace(tzinfo=now.tzinfo)
        # イベントを書けなかった回はプロセス内の時刻で代用する（kanban #82 B3）。
        fallback = self._spoke_at.get(ctx.persona)
        if fallback is not None and (last_spoke is None or fallback > last_spoke):
            last_spoke = fallback
        if (
            last_spoke is not None
            and (now - last_spoke).total_seconds() / 60 < session_config.proactive_cooldown_minutes
        ):
            return None
        return idle

    async def _deliberate(self, ctx: AppContext, idle_minutes: float, now: datetime) -> str:
        """判断用のターンを回して本文を集める（SSE は捨てる）。"""
        session_config = ctx.config.session_config  # type: ignore[union-attr]
        prompt = (
            f"今 {now.strftime('%Y-%m-%d %H:%M')}。{int(idle_minutes)}分話していない。"
            "自分から話しかけるなら1〜2文で書け。話すことがなければ "
            f"{SILENT_MARK} とだけ返せ。用もないのに埋め合わせの挨拶はするな。"
            "質問か、今の自分の居場所・体調・作業の話を1つ混ぜてよい。"
        )
        if session_config.proactive_prompt.strip():
            prompt = f"{prompt}\n{session_config.proactive_prompt.strip()}"

        session_id = f"{PROACTIVE_SESSION_PREFIX}{now.strftime('%Y-%m-%d')}"
        hub = get_turn_hub()
        if not hub.begin_background_turn(ctx.persona):
            # ユーザーターン中は自発ターンを重ねない（ブロック待ちしない。kanban #67）。
            logger.info("proactive: skip — a turn is running (persona=%s)", ctx.persona)
            return ""
        try:
            parts: list[str] = []
            async for sse in ChatService().chat(ctx, ctx.config, session_id, prompt):  # type: ignore[arg-type]
                if not sse.startswith("data: "):
                    continue
                try:
                    payload = json.loads(sse.removeprefix("data: "))
                except ValueError:
                    continue
                kind = payload.get("type")
                if kind == "error":
                    # LLM 失敗時は「⚠ 応答を作れなかった」を自発発言として main に残さない。
                    return ""
                if kind == "text_delta":
                    parts.append(str(payload.get("content") or ""))
            return "".join(parts).strip()
        finally:
            hub.end_background_turn(ctx.persona)

    def _speak(self, ctx: AppContext, text: str, max_messages: int) -> None:
        """main 履歴へ追記し、既存 chat() と同じ形の SSE で届ける。"""
        if not speak_to_main(ctx, text, max_messages, SPOKE_EVENT):
            # イベントを書けなかったので、クールダウンはプロセス内の時刻で代用する。
            self._spoke_at[ctx.persona] = get_now()
