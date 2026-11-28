"""ActivityWorker — 予定が無い時に自分で 1 アクション選んで実行する（kanban #47）。

``ProspectiveWorker`` は ``schedule_task`` で登録済みの ``agent:task`` を走らせるだけで、
「予定が無いときに何をするか」を決める主体が居なかった。こちらは idle な persona に
ついて状態（場所・感情・体調・時間帯）と直近の記憶を読み、LLM に **1 アクションだけ**
選ばせて実行する。

選択肢: ``move`` / ``research`` / ``write_file`` / ``memory_update`` / ``nothing``。
（``ProactiveWorker`` が発話専用なのに対し、こちらは行動。両者は独立に動く。）

判定は 4 段。すべて満たす時だけ判断に進む:

1. ``session_config.autonomy_enabled``（既定 False・自発発言と共通）
   - 続けて ``autonomy.quiet_reason`` で深夜・疲労・痛み・覚醒を確認（止めるなら LLM を呼ばない）
2. 最後の ``chat.message`` から ``activity_idle_minutes`` 以上経過
3. 当日の ``activity.acted`` が ``activity_daily_limit`` 未満
4. 前回の判断から tick 間隔以上経過

結果は ``memory_create`` と ``activity.acted`` イベントに還す。感情・身体の更新経路は
触らない（状態は読むだけ。``move`` が疲労を動かすのは行動の結果）。

注意: 巡回対象は ``AppContextRegistry.personas()``、すなわち **一度でも HTTP/チャットで
アクセスされた persona だけ**（AppContext は遅延生成）。
"""

from __future__ import annotations

import asyncio
import json
import threading
from typing import TYPE_CHECKING, Any

from nous.application.chat.service import ChatService, get_turn_hub
from nous.application.workers.proactive_worker import idle_minutes
from nous.config.settings import get_settings
from nous.domain.memory.session_event import SessionEvent
from nous.domain.memory.session_ids import ACTIVITY_SESSION_PREFIX
from nous.domain.shared.result import Success
from nous.domain.shared.time_utils import get_now
from nous.infrastructure.logging.structured import get_logger
from nous.infrastructure.sqlite.session_event_repo import SessionEventRepository

if TYPE_CHECKING:
    from datetime import datetime

    from nous.application.use_cases import AppContext
    from nous.domain.config.chat_config import ChatConfig

logger = get_logger(__name__)

ACTED_EVENT = "activity.acted"
#: LLM が選べる行動。増やす時は :meth:`ActivityWorker._act` の分岐も足す。
CHOICES = ("move", "research", "write_file", "memory_update", "nothing")


class ActivityWorker:
    """idle な persona に、1 tick 1 アクションだけ実行させる。"""

    def __init__(self) -> None:
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        #: persona → 直前に判断した時刻。
        #: shortcut: 判断間隔は tick と同じ。設定で tick より短くしても詰まらない。
        self._last_check: dict[str, datetime] = {}
        #: (persona, YYYY-MM-DD) → 当日の実行数（イベントを書けなかった分の代替、kanban #82 B3）。
        self._acted_fallback: dict[tuple[str, str], int] = {}

    def _interval(self) -> float:
        """1 tick の間隔（秒）。設定を毎サイクル読み直す（hot reload を次サイクルに効かせる）。"""
        return float(get_settings().workers.activity_interval_seconds)

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="activity-worker")
        self._thread.start()
        logger.info("ActivityWorker started (interval=%ss)", self._interval())

    def stop(self, timeout: float = 5.0) -> None:
        self._stop_event.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=timeout)
        logger.info("ActivityWorker stopped")

    def _run(self) -> None:
        while not self._stop_event.wait(self._interval()):
            try:
                self.run_cycle()
            except Exception:
                logger.exception("ActivityWorker cycle failed")

    def run_cycle(self) -> None:
        """1 サイクル（手動運転・検証用に public）。"""
        from nous.application.use_cases import AppContextRegistry

        for persona in AppContextRegistry.all_personas():
            try:
                ctx = AppContextRegistry.get(persona)
            except Exception:
                # 削除中の PersonaNotFoundError もここで拾う（他ペルソナを止めない）
                logger.exception("ActivityWorker: persona=%s failed", persona)
                continue
            try:
                asyncio.run(self.run_persona(ctx))
            except Exception:
                logger.exception("ActivityWorker: persona=%s action failed", persona)

    async def run_persona(self, ctx: AppContext) -> dict[str, Any] | None:
        """1 persona 分の判断と実行。動いたら結果 dict、動かなければ None。"""
        config = ctx.config
        if config is None:
            return None
        session_config = config.session_config
        if not session_config.autonomy_enabled:
            return None

        now = get_now()
        last_check = self._last_check.get(ctx.persona)
        if last_check is not None:
            if last_check.tzinfo is None:
                last_check = last_check.replace(tzinfo=now.tzinfo)
            if (now - last_check).total_seconds() < self._interval():
                return None

        idle = idle_minutes(ctx, now, session_config.activity_idle_minutes)
        if idle is None:
            return None
        if self._acted_today(ctx, now) >= session_config.activity_daily_limit:
            return None

        from nous.application.workers.autonomy import quiet_reason

        quiet = quiet_reason(ctx, now)
        if quiet is not None:
            logger.info("activity: skip — %s (persona=%s)", quiet, ctx.persona)
            return None

        choice = await self._choose(ctx, config, idle, now)
        if choice is None:
            # 判断できなかったので間隔を進めない (kanban #82 B6)。
            return None
        self._last_check[ctx.persona] = now
        action = str(choice.get("action") or "")
        if action not in CHOICES:
            logger.info("ActivityWorker: persona=%s unknown action %r", ctx.persona, action)
            return None
        if action == "nothing":
            return None

        result = await self._act(ctx, config, action, choice)
        await self._record(ctx, action, choice, result)
        # LLM の JSON は信頼境界。文字列 "false" / "no" / 1 が真になると問いを消してしまう。
        if action == "research" and result.get("status") == "ok" and choice.get("resolves") is True:
            await self._close_question(ctx, choice.get("question"))
        logger.info("ActivityWorker: persona=%s did %s (%s)", ctx.persona, action, choice.get("reason") or "")
        return {"action": action, "result": result, "reason": choice.get("reason") or ""}

    def _acted_today(self, ctx: AppContext, now: datetime) -> int:
        """当日に実行したアクション数（イベントを正とする。再起動で消えない）。"""
        start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        events = SessionEventRepository(ctx.connection).get_by_persona(
            ctx.persona, event_type=ACTED_EVENT, since=start, limit=100
        )
        # イベントを書けなかった回はここで数える（書けないと上限が効かなくなる、kanban #82 B3）。
        return len(events) + self._acted_fallback.get((ctx.persona, now.date().isoformat()), 0)

    def _questions_text(self, ctx: AppContext) -> str:
        """未解決の問いを最大3件、1 行ずつ（各 200 字）。取れなければ空文字。

        答えを書く主体は判断ターンなので、ここでは材料を渡すだけ。
        """
        try:
            from nous.application.wiki.questions import find_open_questions

            found = find_open_questions(ctx)[:3]
        except Exception:
            logger.debug("ActivityWorker: open questions unavailable", exc_info=True)
            return ""
        return "\n".join(f"- {str(m.content)[:200]}" for m in found)

    async def _close_question(self, ctx: AppContext, question: object) -> None:
        """``resolves`` 付きで調査が成功した時だけ、一致する未解決の問いを閉じる。

        一致しなければ何もしない（閉じ間違いより閉じ残しの方が安い）。
        """
        text = str(question or "").strip()
        if not text:
            return
        try:
            from nous.application.wiki.questions import close_open_questions, find_open_questions, question_key_of

            for memory in find_open_questions(ctx):
                content = str(getattr(memory, "content", "") or "")
                if content and (text in content or content in text):
                    await close_open_questions(ctx, ctx.persona, question_key_of(memory))
                    logger.info("ActivityWorker: closed open question (persona=%s)", ctx.persona)
                    return
        except Exception:
            logger.debug("ActivityWorker: closing question failed", exc_info=True)

    def _state_text(self, ctx: AppContext) -> str:
        """場所・感情・体調を 1 行に。取れなければ空文字。"""
        try:
            result = ctx.persona_service.get_context(ctx.persona)
            if not isinstance(result, Success):
                return ""
            state = result.value
        except Exception:
            logger.debug("ActivityWorker: state unavailable", exc_info=True)
            return ""

        bits: list[str] = []
        if getattr(state, "environment", ""):
            bits.append(f"場所={state.environment}")
        if getattr(state, "emotion", ""):
            intensity = getattr(state, "emotion_intensity", 0.0) or 0.0
            bits.append(f"感情={state.emotion}({intensity:.1f})")
        for name, label in (("fatigue", "疲労"), ("warmth", "温かさ"), ("arousal", "緊張")):
            value = getattr(state, name, None)
            if isinstance(value, (int, float)):
                bits.append(f"{label}={value:.1f}")
        for name, label in (("physical_state", "体調"), ("mental_state", "気分")):
            text = getattr(state, name, "")
            if text:
                bits.append(f"{label}={text}")
        return " / ".join(bits)

    def _recent_text(self, ctx: AppContext) -> str:
        """直近の記憶を数件、1 行ずつ。取れなければ空文字。"""
        try:
            result = ctx.memory_service.get_recent(limit=5)
            if not isinstance(result, Success):
                return ""
            return "\n".join(f"- {m.content[:80]}" for m in result.value)
        except Exception:
            logger.debug("ActivityWorker: recent memories unavailable", exc_info=True)
            return ""

    async def _choose(self, ctx: AppContext, config: ChatConfig, idle: float, now: datetime) -> dict[str, Any] | None:
        """判断用のターンを回して 1 アクションを JSON で受け取る（SSE は捨てる）。"""
        session_config = config.session_config
        questions_text = self._questions_text(ctx)
        prompt = (
            f"今 {now.strftime('%Y-%m-%d %H:%M')}、{int(idle)}分ひとりでいる。\n"
            f"今の自分: {self._state_text(ctx) or '不明'}\n"
            f"直近の記憶:\n{self._recent_text(ctx) or 'なし'}\n"
            + (f"\n## 気になっていること\n{questions_text}\n" if questions_text else "")
            + "\nこの時間に自分からやることを1つだけ選べ。次の形の JSON だけを返せ。\n"
            '{"action": "move|research|write_file|memory_update|nothing", '
            '"target": "移動先", "question": "調べる問い", "resolves": false, '
            '"content": "書く内容", "memory_key": "更新する記憶", "reason": "理由"}\n'
            "- move: 移動先を target に書く。\n"
            "- research: question に書いたことをwebで調べる。気になっていることを調べるなら\n"
            "  その問いをそのまま question に写し、答えが出て問いが片付くなら resolves を true にする。\n"
            "- write_file: target にパス、content に中身を書く。\n"
            "- memory_update: memory_key と content を書く。\n"
            "- nothing: 何もしない。reason だけ書く。\n"
            "迷ったら nothing。用もないのに動くな。"
        )
        if session_config.activity_prompt.strip():
            prompt = f"{prompt}\n{session_config.activity_prompt.strip()}"

        hub = get_turn_hub()
        if not hub.begin_background_turn(ctx.persona):
            # ユーザーターン中は自発ターンを重ねない（ブロック待ちしない。kanban #67）。
            logger.info("activity: skip — a turn is running (persona=%s)", ctx.persona)
            return None
        try:
            parts: list[str] = []
            async for sse in ChatService().chat(
                ctx, config, f"{ACTIVITY_SESSION_PREFIX}{now.strftime('%Y-%m-%d')}", prompt
            ):
                if not sse.startswith("data: "):
                    continue
                try:
                    payload = json.loads(sse.removeprefix("data: "))
                except ValueError:
                    continue
                kind = payload.get("type")
                if kind == "error":
                    # 無音で None を返すと原因がログに残らない（kanban #156）。
                    logger.warning(
                        "activity: choose failed — llm error: %s (persona=%s)",
                        payload.get("message") or payload.get("error") or payload,
                        ctx.persona,
                    )
                    return None
                if kind == "text_delta":
                    parts.append(str(payload.get("content") or ""))
            text = "".join(parts)
            if not text.strip():
                logger.warning("activity: choose failed — empty reply (persona=%s)", ctx.persona)
                return None
            parsed = self._parse(text)
            if parsed is None:
                logger.warning("activity: choose failed — unparsable json (persona=%s): %r", ctx.persona, text[:300])
            return parsed
        finally:
            hub.end_background_turn(ctx.persona)

    @staticmethod
    def _parse(text: str) -> dict[str, Any] | None:
        """本文から最初の JSON オブジェクトを拾う。前置きやコードフェンスを許す。"""
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            parsed = json.loads(text[start : end + 1])
        except ValueError:
            return None
        return parsed if isinstance(parsed, dict) else None

    async def _act(self, ctx: AppContext, config: ChatConfig, action: str, choice: dict[str, Any]) -> dict[str, Any]:
        """選ばれたアクションを実行する。tool 側の検証・失敗整形は既存のまま使う。"""
        from nous.application.chat.tools.builtin import execute_tool

        if action == "move":
            return await execute_tool(ctx, config, "move", {"place": str(choice.get("target") or "")})
        if action == "research":
            from nous.application.wiki.research import research as research_web

            question = str(choice.get("question") or choice.get("command") or "")
            found = await research_web(ctx, ctx.persona, question, max_calls=get_settings().explorer.max_tool_calls)
            hits = found.get("hits") or []
            if not hits:
                return {"status": "failed", "reason": str(found.get("reason") or "no_url")}
            return {
                "status": "ok",
                "answer": str(found.get("answer") or ""),
                "hits": [str(hit.get("url") or "") for hit in hits],
            }
        if action == "write_file":
            return await execute_tool(
                ctx,
                config,
                "write_file",
                {"path": str(choice.get("target") or ""), "content": str(choice.get("content") or "")},
            )
        return await execute_tool(
            ctx,
            config,
            "memory_update",
            {"memory_key": str(choice.get("memory_key") or ""), "content": str(choice.get("content") or "")},
        )

    async def _record(self, ctx: AppContext, action: str, choice: dict[str, Any], result: dict[str, Any]) -> bool:
        """やったことを記憶とイベントに還す。失敗しても本体は止めない。"""
        reason = str(choice.get("reason") or "")
        outcome = str(result.get("status") or "")
        subject = choice.get("target") or choice.get("question") or ""
        line = f"自発活動: {action} ({outcome}) {reason} {subject}".strip()
        answer = str(result.get("answer") or "")[:120]
        if answer:
            line = f"{line} → {answer}"
        try:
            await ctx.memory_service.create_memory(
                content=line[:400],
                importance=0.3,
                tags=["self_activity"],
                persona=ctx.persona,
                kind="episodic",
                source_type="llm_inferred",
            )
        except Exception:
            logger.debug("ActivityWorker: memory_create failed", exc_info=True)
        recorded = True
        try:
            SessionEventRepository(ctx.connection).insert(
                SessionEvent(
                    session_id="main",
                    persona=ctx.persona,
                    event_type=ACTED_EVENT,
                    timestamp=get_now(),
                    summary=line[:200],
                )
            )
        except Exception:
            # 日次上限はイベント件数で数えるので、書けないと上限が消える (kanban #82 B3)。
            recorded = False
            key = (ctx.persona, get_now().date().isoformat())
            self._acted_fallback[key] = self._acted_fallback.get(key, 0) + 1
            logger.warning("ActivityWorker: failed to record %s", ACTED_EVENT, exc_info=True)
        return recorded
