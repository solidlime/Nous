"""
AgentLoop — 2層自律トリガー統合ループ。

意識ティック（15-90分ランダム）+ ドライブ閾値越え + 外部イベント処理を
1分ポーリングで統合管理する。

内部コンポーネント（EventBus / AgentScheduler / ContextBuilder / ActionExecutor）は
初回 run() 時に _lazy_init() で生成する（循環インポート回避）。
"""

import asyncio
import json
import logging
import random
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class AgentLoop:
    """AIキャラクターの自律稼働ループ。

    Args:
        persona: ペルソナ名。
        llm_router: LLMRouter インスタンス。
        memory_db: MemoryDB インスタンス。
        conv_db: ConversationDB インスタンス。
        emotional_model: EmotionalModel インスタンス。
        drive_system: DriveSystem インスタンス。
        goal_manager: GoalManager インスタンス。
        decision_engine: DecisionEngine インスタンス。
        config: Nous 設定 dict（load_config() の返り値）。
        psychology_engine: PsychologyEngine インスタンス（None の場合は individual モデルを使用）。
    """

    def __init__(
        self,
        persona: str,
        llm_router: Any,
        memory_db: Any,
        conv_db: Any,
        emotional_model: Any,
        drive_system: Any,
        goal_manager: Any,
        decision_engine: Any,
        config: dict,
        psychology_engine: Optional[Any] = None,
    ) -> None:
        self._persona = persona
        self._llm_router = llm_router
        self._memory_db = memory_db
        self._conv_db = conv_db
        self._decision_engine = decision_engine
        self._config = config

        # PsychologyEngine が渡された場合は内部モデルを参照することで
        # 感情更新が AppraisalEngine → PAD パイプラインを通るようになる
        if psychology_engine is not None:
            self._psychology_engine = psychology_engine
            self._emotional_model = psychology_engine.emotional
            self._drive_system = psychology_engine.drives
            self._goal_manager = psychology_engine.goals
        else:
            self._psychology_engine = None
            self._emotional_model = emotional_model
            self._drive_system = drive_system
            self._goal_manager = goal_manager

        # ループ内部状態
        self._running = False
        self._last_consciousness_tick: Optional[datetime] = None
        self._last_drive_tick: Optional[datetime] = None
        # 次の意識ティックまでの間隔（分）。起動時は 30 分に設定する
        self._next_tick_interval: float = 30.0
        self._action_log: List[Dict[str, Any]] = []

        # 遅延初期化するコンポーネント（_lazy_init() で生成）
        self._event_bus: Optional[Any] = None
        self._scheduler: Optional[Any] = None
        self._context_builder: Optional[Any] = None
        self._action_executor: Optional[Any] = None

    # ── 遅延初期化 ────────────────────────────────────────────────────────────

    def _lazy_init(self) -> None:
        """初回 run() 時に内部コンポーネントを生成する。

        循環インポートを避けるため、コンストラクタではなくここで import する。
        """
        from agent.action_executor import ActionExecutor
        from agent.context_builder import ContextBuilder
        from agent.event_bus import EventBus
        from agent.scheduler import AgentScheduler

        self._event_bus = EventBus()
        self._scheduler = AgentScheduler(self._event_bus, self._config)
        self._context_builder = ContextBuilder(
            persona=self._persona,
            memory_db=self._memory_db,
            conv_db=self._conv_db,
            emotional_model=self._emotional_model,
            drive_system=self._drive_system,
            goal_manager=self._goal_manager,
            config=self._config,
        )
        self._action_executor = ActionExecutor(
            persona=self._persona,
            memory_db=self._memory_db,
            conv_db=self._conv_db,
            llm_router=self._llm_router,
            config=self._config,
        )

    # ── メインループ ──────────────────────────────────────────────────────────

    async def run(self) -> None:
        """エージェントのメインループ。

        1 分ごとに以下を順番にチェックする:
        1. EventBus に溜まったイベントを処理（最優先）。
        2. ドライブを時間経過で更新。
        3. 閾値を超えたドライブがあれば _drive_overflow_tick() を呼ぶ。
        4. 意識ティック判定を行い、必要なら _consciousness_tick() を呼ぶ。

        asyncio.CancelledError を受け取ったらループを終了する。
        """
        self._lazy_init()
        self._running = True
        self._scheduler.start()
        logger.info(f"AgentLoop 開始: {self._persona}")

        try:
            while self._running:
                # 外部イベント処理（最優先 — 溜まっているイベントをすべて処理してから次へ）
                event = self._event_bus.try_get_nowait()
                if event is not None:
                    await self._handle_event(event)
                    continue

                # ドライブ更新（1分ごと）
                await self._tick_drives()

                # ドライブ閾値越えチェック
                if self._psychology_engine is not None:
                    triggered = self._psychology_engine.drives.get_triggered_drives()
                else:
                    triggered = self._drive_system.get_triggered_drives()
                if triggered:
                    await self._drive_overflow_tick(triggered)

                # 意識ティック判定
                if self._should_fire_consciousness_tick():
                    await self._consciousness_tick()

                # 感情の自然減衰（毎分 neutral に向かってゆっくり戻す）
                try:
                    if self._psychology_engine is not None:
                        self._psychology_engine.decay(decay_rate=0.03)
                    else:
                        self._emotional_model.decay(decay_rate=0.03)
                except Exception as e:
                    logger.debug(f"感情減衰失敗: {e}")

                await asyncio.sleep(60)  # 1分ポーリング

        except asyncio.CancelledError:
            pass
        finally:
            self._running = False
            self._scheduler.stop()
            logger.info(f"AgentLoop 停止: {self._persona}")

    # ── 外部 API ─────────────────────────────────────────────────────────────

    async def handle_web_message(self, content: str, user_id: str = "web_user") -> str:
        """Web チャット UI からのメッセージを処理して返答文字列を返す。

        ペルソナ設定で tools_enabled=True の場合、ツール呼び出しループを実行する。

        Args:
            content: ユーザーが入力したメッセージ。
            user_id: ユーザーの識別子（デフォルト "web_user"）。

        Returns:
            LLM が生成した返答文字列。LLM が利用不可の場合は "[LLM unavailable]"。
        """
        if self._context_builder is None:
            self._lazy_init()

        # 会話スレッドを取得してユーザーターンを保存
        max_silence = self._config.get("conversation", {}).get("max_silence_hours", 8.0)
        thread = self._conv_db.get_or_create_active_thread(
            self._persona, max_silence_hours=max_silence
        )
        self._conv_db.add_turn(thread.id, "web_ui", "user", content, user_id=user_id)

        # ペルソナ設定でツール使用が有効かチェック
        persona_cfg = self._config.get("personas", {}).get(self._persona, {})
        tools_enabled = persona_cfg.get("tools_enabled", False)

        # メッセージリストを構築
        ctx_messages = await self._context_builder.build_web_context(content)
        from llm.base import Message
        msgs = [Message(role=m["role"], content=m["content"]) for m in ctx_messages]

        tools = self._get_available_tools() if tools_enabled else None

        # LLM 呼び出し（ツールループ: 最大 5 ラウンド）
        response = await self._llm_router.generate(msgs, task_type="web_reply", tools=tools)
        for _ in range(5):
            if not response.tool_calls:
                break
            # ツールを実行して結果をメッセージに追加
            tool_results = await self._execute_tool_calls(response.tool_calls)
            msgs.append(Message(role="assistant", content=response.content or ""))
            for tr in tool_results:
                msgs.append(Message(role="tool", content=json.dumps(tr, ensure_ascii=False)))
            response = await self._llm_router.generate(msgs, task_type="web_reply", tools=tools)

        # アシスタントターンを保存
        self._conv_db.add_turn(thread.id, "web_ui", "assistant", response.content)

        # 感情モデル更新（PsychologyEngine 経由で OCC 評価パイプラインを通す）
        try:
            if self._psychology_engine is not None:
                self._psychology_engine.process_event("positive_interaction")
            else:
                self._emotional_model.update("positive_interaction", 0.7)
        except Exception as e:
            logger.warning(f"[{self._persona}] 感情モデル更新失敗: {e}")

        return response.content

    def _get_available_tools(self) -> List[dict]:
        """ペルソナが会話中に使用できるツール定義を返す（OpenAI function calling 形式）。"""
        return [
            {
                "type": "function",
                "function": {
                    "name": "search_memory",
                    "description": "過去の記憶を検索する。会話に関連する情報を思い出すのに使う。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "検索クエリ"},
                            "limit": {"type": "integer", "description": "最大件数 (デフォルト: 5)"},
                        },
                        "required": ["query"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "save_memory",
                    "description": "重要な情報を記憶に保存する。会話から得た重要な事実を記録するのに使う。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "content": {"type": "string", "description": "保存する内容"},
                            "importance": {"type": "number", "description": "重要度 0.0-1.0 (デフォルト: 0.5)"},
                            "tags": {"type": "array", "items": {"type": "string"}, "description": "タグリスト"},
                        },
                        "required": ["content"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_current_state",
                    "description": "現在の感情状態・ドライブ値を取得する。",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
        ]

    async def _execute_tool_calls(self, tool_calls: List[Dict[str, Any]]) -> List[dict]:
        """ツール呼び出しを実行して結果リストを返す。

        Returns:
            各要素は {"tool_call_id": str, "name": str, "content": str} の形式。
        """
        results = []
        for tc in tool_calls:
            fn_name = tc.get("name", "")
            args = tc.get("arguments", {})
            tool_id = tc.get("id", fn_name)
            try:
                if fn_name == "search_memory":
                    result = await self._tool_search_memory(**args)
                elif fn_name == "save_memory":
                    result = await self._tool_save_memory(**args)
                elif fn_name == "get_current_state":
                    result = self._tool_get_current_state()
                else:
                    result = {"error": f"unknown tool: {fn_name}"}
            except Exception as e:
                result = {"error": str(e)}
            results.append({
                "tool_call_id": tool_id,
                "name": fn_name,
                "content": json.dumps(result, ensure_ascii=False),
            })
        return results

    async def _tool_search_memory(self, query: str, limit: int = 5) -> dict:
        """記憶を検索する内部ツール実装。"""
        try:
            entries = self._memory_db.search(query, limit=limit)
            return {
                "results": [
                    {"key": e.key, "content": e.content[:300], "importance": e.importance, "tags": e.tags}
                    for e in entries
                ]
            }
        except Exception as e:
            return {"error": str(e)}

    async def _tool_save_memory(self, content: str, importance: float = 0.5, tags: list = None) -> dict:
        """記憶を保存する内部ツール実装。"""
        try:
            from memory.schema import MemoryEntry
            from datetime import datetime
            key = self._memory_db.generate_key()
            entry = MemoryEntry(
                key=key,
                content=content,
                created_at=datetime.now().isoformat(),
                updated_at=datetime.now().isoformat(),
                importance=importance,
                tags=tags or [],
            )
            success = self._memory_db.save(entry)
            return {"success": success, "key": key}
        except Exception as e:
            return {"error": str(e)}

    def _tool_get_current_state(self) -> dict:
        """現在の心理状態を返す内部ツール実装。"""
        result: Dict[str, Any] = {"persona": self._persona}
        try:
            em_state = self._emotional_model.state
            result["emotion"] = {
                "surface": em_state.surface_emotion,
                "mood": em_state.mood,
            }
        except Exception:
            pass
        try:
            ds_state = self._drive_system.state
            result["drives"] = {
                "curiosity": ds_state.curiosity,
                "boredom": ds_state.boredom,
                "connection": ds_state.connection,
            }
        except Exception:
            pass
        return result

    async def trigger_task(self, task_type: str, params: Optional[dict] = None) -> Any:
        """外部から手動でタスクを投入する（REST API 経由で呼ばれる）。

        Args:
            task_type: タスク種別文字列。
                "consciousness_tick" — 意識ティックを強制発火。
                "morning_greeting"  — 朝挨拶タスクを発火。
                "daily_diary"       — 日次日記タスクを実行。
                "anniversary_check" — 記念日チェックを実行。
                "discord_send"      — Discord にメッセージ送信（params: channel_id, message）。
                "speak"             — VOICEVOX で発話（params: text）。
            params: タスク固有のパラメータ dict。

        Returns:
            タスクの実行結果文字列。
        """
        params = params or {}

        if task_type == "consciousness_tick":
            await self._consciousness_tick()
            return "consciousness_tick fired"

        if task_type == "morning_greeting":
            from agent.tasks.morning_greeting import run_morning_greeting
            return await run_morning_greeting(self, self._config)

        if task_type == "daily_diary":
            from agent.tasks.daily_diary import run_daily_diary
            return await run_daily_diary(
                self, self._llm_router, self._memory_db, self._persona
            )

        if task_type == "anniversary_check":
            from agent.tasks.anniversary_check import run_anniversary_check
            return await run_anniversary_check(
                self, self._memory_db, self._llm_router, self._persona
            )

        if task_type == "discord_send":
            if self._action_executor is None:
                self._lazy_init()
            from agent.action_executor import Action
            action = Action(
                type="send_discord",
                content=params.get("message", ""),
                metadata={"channel_id": params.get("channel_id")},
            )
            return await self._action_executor.execute(action)

        if task_type == "speak":
            if self._action_executor is None:
                self._lazy_init()
            from agent.action_executor import Action
            action = Action(type="speak", content=params.get("text", ""))
            return await self._action_executor.execute(action)

        logger.warning(f"[{self._persona}] trigger_task: 未知のタスク種別: {task_type}")
        return f"unknown task_type: {task_type}"

    async def get_status(self) -> dict:
        """エージェントの稼働状態を返す。

        Returns:
            稼働状態・最終ティック時刻・次ティックまでの時間・
            キューサイズ・アクションログ数・ドライブ値を含む dict。
        """
        drives: Dict[str, float] = {}
        if self._drive_system is not None:
            state = self._drive_system.state
            drives = {
                "curiosity": state.curiosity,
                "boredom": state.boredom,
                "connection": state.connection,
                "expression": state.expression,
                "mastery": state.mastery,
            }

        return {
            "persona": self._persona,
            "status": "running" if self._running else "stopped",
            "last_consciousness_tick": (
                self._last_consciousness_tick.isoformat()
                if self._last_consciousness_tick
                else None
            ),
            "next_tick_in_minutes": self._get_minutes_until_next_tick(),
            "event_queue_size": (
                self._event_bus.qsize() if self._event_bus is not None else 0
            ),
            "action_log_count": len(self._action_log),
            "drives": drives,
        }

    # ── 意識ティック判定 ──────────────────────────────────────────────────────

    def _should_fire_consciousness_tick(self) -> bool:
        """意識ティックを発火すべきかどうかを返す。

        最後のティックから _next_tick_interval 分以上経過していれば True。
        consciousness.enabled が False の場合は常に False。
        """
        consciousness_cfg = self._config.get("consciousness", {})
        if not consciousness_cfg.get("enabled", True):
            return False
        if self._last_consciousness_tick is None:
            return True
        elapsed = (
            datetime.now() - self._last_consciousness_tick
        ).total_seconds() / 60
        return elapsed >= self._next_tick_interval

    def _randomize_next_tick_interval(self) -> None:
        """次の意識ティック間隔を設定範囲内でランダムに設定する。

        consciousness.interval_min_min（デフォルト 15）から
        consciousness.interval_max_min（デフォルト 60）の範囲で選ぶ。
        """
        consciousness_cfg = self._config.get("consciousness", {})
        min_min = consciousness_cfg.get("interval_min_min", 15)
        max_min = consciousness_cfg.get("interval_max_min", 60)
        self._next_tick_interval = random.uniform(min_min, max_min)

    def _get_minutes_until_next_tick(self) -> float:
        """次の意識ティックまでの残り分数を返す。未発火なら 0.0 を返す。"""
        if self._last_consciousness_tick is None:
            return 0.0
        elapsed = (
            datetime.now() - self._last_consciousness_tick
        ).total_seconds() / 60
        return max(0.0, self._next_tick_interval - elapsed)

    # ── ティック処理 ──────────────────────────────────────────────────────────

    async def _consciousness_tick(self) -> None:
        """意識ティック処理。

        1. コンテキストを構築して LLM に渡す。
        2. 返答を JSON パースしてアクションを決定する。
        3. "nothing" でなければ ActionExecutor で実行してアクションログに残す。
        """
        self._last_consciousness_tick = datetime.now()
        self._randomize_next_tick_interval()

        try:
            context = await self._context_builder.build_consciousness_context()
            from llm.base import Message
            response = await self._llm_router.generate(
                messages=[Message(role="user", content=context)],
                task_type="consciousness",
            )

            decision = self._parse_consciousness_response(response.content)

            if decision.get("action") == "nothing":
                logger.debug(f"意識ティック: nothing ({self._persona})")
                return

            from agent.action_executor import Action
            action = Action(
                type=decision.get("action", "nothing"),
                content=decision.get("content"),
                reason=decision.get("reason"),
                metadata={"source": "consciousness_tick"},
            )
            result = await self._action_executor.execute(action)
            self._action_log.append({
                "type": "consciousness_tick",
                "action": action.type,
                "result": result,
                "at": datetime.now().isoformat(),
            })
            logger.info(f"意識ティック実行: {action.type} — {result}")

        except Exception as e:
            logger.error(f"意識ティックエラー [{self._persona}]: {e}", exc_info=True)

    async def _drive_overflow_tick(self, triggered_drives: List[str]) -> None:
        """ドライブ閾値越えティック処理。

        閾値を超えたドライブ名を前置したコンテキストで LLM を呼び出し、
        アクションを決定する。実行後はトリガーしたドライブを 0.3 消費する。

        Args:
            triggered_drives: 閾値を超えたドライブ名のリスト。
        """
        try:
            context = await self._context_builder.build_consciousness_context()
            drives_info = "、".join(triggered_drives)
            context = f"[ドライブ高まり: {drives_info}]\n\n" + context

            from llm.base import Message
            response = await self._llm_router.generate(
                messages=[Message(role="user", content=context)],
                task_type="consciousness",
            )
            decision = self._parse_consciousness_response(response.content)

            if decision.get("action") != "nothing":
                # トリガーしたドライブを消費してから実行
                for drive in triggered_drives:
                    self._drive_system.consume(drive, 0.3)

                from agent.action_executor import Action
                action = Action(
                    type=decision.get("action", "nothing"),
                    content=decision.get("content"),
                    reason=decision.get("reason"),
                    metadata={
                        "source": "drive_overflow",
                        "drives": triggered_drives,
                    },
                )
                result = await self._action_executor.execute(action)
                self._action_log.append({
                    "type": "drive_overflow",
                    "drives": triggered_drives,
                    "action": action.type,
                    "result": result,
                    "at": datetime.now().isoformat(),
                })
                logger.info(
                    f"ドライブオーバーフロー実行: drives={triggered_drives}, "
                    f"action={action.type}"
                )

        except Exception as e:
            logger.error(
                f"ドライブオーバーフロータックエラー [{self._persona}]: {e}",
                exc_info=True,
            )

    async def _tick_drives(self) -> None:
        """ドライブを時間経過（elapsed_hours）で更新する（約1分ごとに呼ばれる）。"""
        now = datetime.now()
        if self._last_drive_tick is None:
            self._last_drive_tick = now
            return
        elapsed_hours = (now - self._last_drive_tick).total_seconds() / 3600
        if self._psychology_engine is not None:
            self._psychology_engine.tick(elapsed_hours)
        else:
            self._drive_system.tick(elapsed_hours)
        self._last_drive_tick = now

    # ── イベントハンドラー ────────────────────────────────────────────────────

    async def _handle_event(self, event: Any) -> None:
        """EventBus から取り出したイベントをルーティングする。

        Args:
            event: AgentEvent インスタンス。
        """
        from agent.event_bus import EventType
        try:
            if event.event_type == EventType.DISCORD_MESSAGE:
                await self._handle_discord_message(event)
            elif event.event_type == EventType.CONSCIOUSNESS_TICK:
                await self._consciousness_tick()
            elif event.event_type == EventType.WEBHOOK_RECEIVED:
                await self._handle_webhook(event)
            elif event.event_type == EventType.SCHEDULE_TRIGGER:
                await self._handle_schedule_trigger(event)
            else:
                logger.debug(
                    f"[{self._persona}] 未処理イベント: {event.event_type}"
                )
        except Exception as e:
            logger.error(
                f"イベント処理エラー [{self._persona}]: {e}", exc_info=True
            )

    async def _handle_discord_message(self, event: Any) -> None:
        """Discord メッセージイベントを処理して返答を送信する。

        1. 会話 DB にユーザーターンを保存する。
        2. コンテキストを構築して LLM で返答を生成する。
        3. アシスタントターンを保存して Discord に送信する。
        4. 感情モデルを更新する（失敗しても継続）。

        Args:
            event: EventType.DISCORD_MESSAGE の AgentEvent。
        """
        content = event.data.get("content", "")
        user_id = event.data.get("user_id", "unknown")
        channel_id = event.data.get("channel_id", "")

        # 会話 DB に保存
        max_silence = self._config.get("conversation", {}).get(
            "max_silence_hours", 8.0
        )
        thread = self._conv_db.get_or_create_active_thread(
            self._persona, max_silence_hours=max_silence
        )
        self._conv_db.add_turn(
            thread.id, "discord", "user", content,
            channel_id=channel_id, user_id=user_id,
        )

        # コンテキスト構築 + LLM 返答生成
        ctx_messages = await self._context_builder.build_web_context(content)
        from llm.base import Message
        msgs = [Message(role=m["role"], content=m["content"]) for m in ctx_messages]
        response = await self._llm_router.generate(msgs, task_type="discord_reply")

        # 返答を会話 DB に保存
        self._conv_db.add_turn(thread.id, "discord", "assistant", response.content)

        # Discord に送信（ActionExecutor 経由）
        from agent.action_executor import Action
        await self._action_executor.execute(
            Action(
                type="send_discord",
                content=response.content,
                metadata={"channel_id": channel_id},
            )
        )

        # 感情更新（PsychologyEngine 経由で OCC 評価パイプラインを通す）
        try:
            if self._psychology_engine is not None:
                self._psychology_engine.process_event("discord_message")
            else:
                self._emotional_model.update("discord_message", 0.3)
        except Exception as e:
            logger.warning(f"[{self._persona}] 感情モデル更新失敗: {e}")

    async def _handle_webhook(self, event: Any) -> None:
        """Webhook イベントを処理する（現在はログのみ）。

        Args:
            event: EventType.WEBHOOK_RECEIVED の AgentEvent。
        """
        logger.info(f"Webhook 受信 [{self._persona}]: {event.data}")

    async def _handle_schedule_trigger(self, event: Any) -> None:
        """スケジュールトリガーイベントを処理する。

        event.data["task"] でタスク種別を判定して trigger_task() に委譲する。

        Args:
            event: EventType.SCHEDULE_TRIGGER の AgentEvent。
        """
        task_name = event.data.get("task", "")
        logger.info(f"スケジュールトリガー [{self._persona}]: {task_name}")
        try:
            await self.trigger_task(task_name)
        except Exception as e:
            logger.error(
                f"スケジュールタスク実行エラー [{self._persona}] {task_name}: {e}",
                exc_info=True,
            )

    # ── LLM 返答パース ────────────────────────────────────────────────────────

    def _parse_consciousness_response(self, content: str) -> dict:
        """LLM の意識ティック返答から JSON を抽出してパースする。

        JSON ブロックが見つからない場合や "nothing" を含む場合は
        {"action": "nothing"} を返す。

        Args:
            content: LLM が生成したテキスト。

        Returns:
            "action" キーを含む dict。
        """
        json_match = re.search(r'\{[^{}]*"action"[^{}]*\}', content, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group())
            except Exception:
                pass
        if "nothing" in content.lower():
            return {"action": "nothing"}
        return {"action": "nothing"}
