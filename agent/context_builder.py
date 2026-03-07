"""
LLM コンテキスト構築器。

意識ティック・イベント処理・Web チャットそれぞれに対して
LLM に渡すプロンプト文字列または messages リストを生成する。

EmotionalModel・DriveSystem・GoalManager・ConversationDB・MemoryDB から
最新状態を取得してテンプレートに埋め込む。
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from agent.event_bus import AgentEvent
from agent.tasks.consciousness_tick import get_time_context
from memory.conversation_db import ConversationDB
from memory.db import MemoryDB
from psychology.drive_system import DriveSystem
from psychology.emotional_model import EmotionalModel
from psychology.goal_manager import Goal, GoalManager

logger = logging.getLogger(__name__)

# 意識ティックプロンプトのテンプレート。
# ContextBuilder.build_consciousness_context() がフィールドを埋めて使用する。
CONSCIOUSNESS_PROMPT = """\
あなたは{persona}。今この瞬間、何かしたい気分はある？

[現在の状態]
時刻: {datetime} ({time_context})
感情: {surface_emotion}（強度: {intensity}）
気分: {mood}

[ドライブ状態]
好奇心: {curiosity:.2f}  退屈: {boredom:.2f}  連帯感: {connection:.2f}
表現欲: {expression:.2f}  習熟欲: {mastery:.2f}

[アクティブゴール]
{active_goals}

[直近の会話（最新5件）]
{recent_conversation}

[最近の記憶（直近5件）]
{recent_memories}

---
今この瞬間、何かしたい気分があれば行動を決めてください。
なければ "nothing" を返してください。

行動がある場合のみ JSON を出力:
{{"action": "send_discord|save_memory|speak|write_diary|nothing", "content": "...", "reason": "..."}}\
"""


class ContextBuilder:
    """LLM に渡すコンテキストを組み立てるクラス。

    Args:
        persona: ペルソナ名。
        memory_db: MemoryDB インスタンス。
        conv_db: ConversationDB インスタンス。
        emotional_model: EmotionalModel インスタンス。
        drive_system: DriveSystem インスタンス。
        goal_manager: GoalManager インスタンス。
        config: Nous 設定 dict。
    """

    def __init__(
        self,
        persona: str,
        memory_db: MemoryDB,
        conv_db: ConversationDB,
        emotional_model: EmotionalModel,
        drive_system: DriveSystem,
        goal_manager: GoalManager,
        config: dict,
    ) -> None:
        self._persona = persona
        self._memory_db = memory_db
        self._conv_db = conv_db
        self._emotional_model = emotional_model
        self._drive_system = drive_system
        self._goal_manager = goal_manager
        self._config = config

    async def build_consciousness_context(self) -> str:
        """意識ティック用プロンプトを生成する。

        現在の時刻・感情状態・ドライブ値・アクティブゴール・
        直近会話・直近記憶を CONSCIOUSNESS_PROMPT テンプレートに埋め込む。

        Returns:
            LLM に渡す完成済みプロンプト文字列。
        """
        now = datetime.now()
        state = self._emotional_model.state
        drive = self._drive_system.state

        # アクティブゴールを箇条書き形式に変換
        goals = self._goal_manager.get_active_goals()
        if goals:
            goals_text = "\n".join(
                f"- [{g.goal_type}] {g.title} (進捗: {g.progress:.0%})"
                for g in goals[:5]
            )
        else:
            goals_text = "（なし）"

        # 直近会話（最新スレッドから5件）
        recent_conv_text = self._get_recent_conversation_text(limit=5)

        # 直近記憶（5件）
        recent_mems = self._memory_db.get_recent(limit=5)
        if recent_mems:
            mems_text = "\n".join(
                f"- {m.content[:80]}{'...' if len(m.content) > 80 else ''}"
                for m in recent_mems
            )
        else:
            mems_text = "（なし）"

        return CONSCIOUSNESS_PROMPT.format(
            persona=self._persona,
            datetime=now.strftime("%Y-%m-%d %H:%M"),
            time_context=get_time_context(now),
            surface_emotion=state.surface_emotion,
            intensity=f"{state.surface_intensity:.2f}",
            mood=state.mood,
            curiosity=drive.curiosity,
            boredom=drive.boredom,
            connection=drive.connection,
            expression=drive.expression,
            mastery=drive.mastery,
            active_goals=goals_text,
            recent_conversation=recent_conv_text,
            recent_memories=mems_text,
        )

    async def build_event_context(
        self,
        event: AgentEvent,
        relevant_memories: Optional[List[Any]] = None,
    ) -> str:
        """イベント処理用プロンプトを生成する。

        意識ティックプロンプトにイベント詳細・関連記憶を前置して返す。

        Args:
            event: 処理対象のイベント。
            relevant_memories: 事前に検索した関連記憶（省略可）。

        Returns:
            LLM に渡すプロンプト文字列。
        """
        base = await self.build_consciousness_context()

        # イベント情報を先頭に付加
        event_section = (
            f"[受信イベント: {event.event_type.value}]\n"
            f"データ: {event.data}\n\n"
        )

        # 関連記憶があれば追記
        if relevant_memories:
            mem_lines = "\n".join(
                f"- {m.content[:80]}{'...' if len(m.content) > 80 else ''}"
                for m in relevant_memories[:5]
            )
            event_section += f"[関連記憶]\n{mem_lines}\n\n"

        return event_section + base

    async def build_web_context(self, user_message: str) -> List[Dict[str, str]]:
        """Web チャット用の messages リストを生成する。

        アクティブスレッドの直近10件を取得して会話履歴を組み立て、
        末尾にユーザーの新規メッセージを追加する。
        先頭にシステムプロンプトを挿入する。

        Args:
            user_message: Web UI から受け取ったユーザー入力。

        Returns:
            [{"role": "system"|"user"|"assistant", "content": ...}, ...] 形式のリスト。
            最初の要素は role="system"、最後の要素は role="user"。
        """
        max_silence = self._config.get("conversation", {}).get(
            "max_silence_hours", 8.0
        )
        thread = self._conv_db.get_or_create_active_thread(
            self._persona, max_silence_hours=max_silence
        )

        # システムプロンプトを取得（ペルソナ設定 > デフォルト）
        persona_cfg = self._config.get("personas", {}).get(self._persona, {})
        system_prompt = persona_cfg.get("system_prompt") or self._build_base_prompt()

        # 直近10件の会話ターンを取得（get_recent_turns は古い順で返す）
        turns = self._conv_db.get_recent_turns(thread.id, limit=10)
        messages: List[Dict[str, str]] = [
            {"role": "system", "content": system_prompt},
        ]
        messages.extend(
            {"role": t.role, "content": t.content} for t in turns
        )

        # 新規ユーザーメッセージを末尾に追加
        messages.append({"role": "user", "content": user_message})

        return messages

    # ── 内部ヘルパー ──────────────────────────────────────────────────────────

    def _build_base_prompt(self) -> str:
        """デフォルトのシステムプロンプトを生成する。"""
        try:
            state = self._emotional_model.state
            emotion_ctx = (
                f"現在の感情: {state.surface_emotion}（強度 {state.surface_intensity:.1f}）、"
                f"気分: {state.mood}"
            )
        except Exception:
            emotion_ctx = ""
        lines = [
            f"あなたは{self._persona}。",
            "Nous AIキャラクターシステムで動作するAIアシスタント。",
        ]
        if emotion_ctx:
            lines.append(emotion_ctx)
        return "\n".join(lines)

    def _get_recent_conversation_text(self, limit: int = 5) -> str:
        """直近の会話ターンを人間が読みやすい形式の文字列に変換する。

        アクティブスレッドが存在しない場合は「（なし）」を返す。

        Args:
            limit: 取得する最大ターン数。

        Returns:
            整形済み会話テキスト。
        """
        try:
            max_silence = self._config.get("conversation", {}).get(
                "max_silence_hours", 8.0
            )
            thread = self._conv_db.get_or_create_active_thread(
                self._persona, max_silence_hours=max_silence
            )
            turns = self._conv_db.get_recent_turns(thread.id, limit=limit)
            if not turns:
                return "（なし）"
            lines = []
            for t in turns:
                role_label = "あなた" if t.role == "assistant" else "相手"
                preview = t.content[:60] + ("..." if len(t.content) > 60 else "")
                lines.append(f"{role_label}: {preview}")
            return "\n".join(lines)
        except Exception as e:
            logger.warning(f"直近会話取得失敗 [{self._persona}]: {e}")
            return "（取得失敗）"
