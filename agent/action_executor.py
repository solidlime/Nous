"""
アクション実行ディスパッチャー。

意識ティック・ドライブオーバーフロー・イベント処理で決定したアクションを
実際の出力（Discord 送信・記憶保存・音声発話・日記書き込み）に変換する。

discord_bot と voice_adapter は後から set_* メソッドで注入するため、
初期化時には None で構わない。
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


@dataclass
class Action:
    """AgentLoop から ActionExecutor に渡すアクション記述。

    type: 実行するアクション種別。
        "send_discord" — Discord チャンネルにメッセージ送信。
        "save_memory"  — 記憶 DB に内容を保存。
        "speak"        — VOICEVOX で音声合成・発話。
        "write_diary"  — 日記エントリとして記憶に保存。
        "nothing"      — 何もしない（スキップ）。
        その他          — unknown として処理しログに残す。
    content: アクションの主要テキスト内容。
    reason: このアクションを選んだ理由（ログ・記憶の補足情報に使用）。
    metadata: アクション種別固有の追加パラメータ（channel_id 等）。
    """
    type: str
    content: Optional[str] = None
    reason: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class ActionExecutor:
    """アクションを実際の出力に変換するディスパッチャー。

    Args:
        persona: ペルソナ名。
        memory_db: MemoryDB インスタンス（記憶保存に使用）。
        conv_db: ConversationDB インスタンス（会話ターン保存に使用）。
        llm_router: LLMRouter インスタンス（日記生成等に使用）。
        config: Nous 設定 dict。
    """

    def __init__(
        self,
        persona: str,
        memory_db: Any,  # memory.db.MemoryDB
        conv_db: Any,    # memory.conversation_db.ConversationDB
        llm_router: Any,  # llm.router.LLMRouter
        config: dict,
    ) -> None:
        self._persona = persona
        self._memory_db = memory_db
        self._conv_db = conv_db
        self._llm_router = llm_router
        self._config = config
        # 後から注入するアダプター（None でも動作する）
        self._discord_bot: Optional[Any] = None
        self._voice_adapter: Optional[Any] = None

    def set_discord_bot(self, bot: Any) -> None:
        """Discord Bot を後から注入する。"""
        self._discord_bot = bot

    def set_voice_adapter(self, adapter: Any) -> None:
        """VOICEVOX アダプターを後から注入する。"""
        self._voice_adapter = adapter

    async def execute(self, action: Action) -> str:
        """アクションを実行して結果の説明文字列を返す。

        各アクションタイプに対応するプライベートメソッドに委譲する。
        未知のタイプはログに残して "unknown action: {type}" を返す。

        Args:
            action: 実行するアクション。

        Returns:
            実行結果を表す文字列。
        """
        if action.type == "send_discord":
            return await self._send_discord(action)
        if action.type == "save_memory":
            return await self._save_memory(action)
        if action.type == "speak":
            return await self._speak(action)
        if action.type == "write_diary":
            return await self._write_diary(action)
        if action.type == "nothing":
            return "nothing"
        logger.warning(f"ActionExecutor: 未知のアクション種別 [{self._persona}]: {action.type}")
        return f"unknown action: {action.type}"

    # ── 個別アクション実装 ────────────────────────────────────────────────────

    async def _send_discord(self, action: Action) -> str:
        """Discord チャンネルにメッセージを送信する。

        _discord_bot が None の場合はログ出力のみ行い送信しない。
        channel_id は action.metadata["channel_id"] から取得する。
        """
        content = action.content or ""
        channel_id_raw = action.metadata.get("channel_id")

        if self._discord_bot is None:
            logger.info(
                f"[{self._persona}] Discord Bot 未設定のため送信スキップ: "
                f"channel={channel_id_raw}, content={content[:50]}"
            )
            return "discord_bot not set (log only)"

        if not channel_id_raw:
            # channel_id が未指定の場合は設定のデフォルトチャンネルを使う
            discord_cfg = self._config.get("discord", {})
            channel_id_raw = discord_cfg.get("channel_id")

        if not channel_id_raw:
            logger.warning(f"[{self._persona}] Discord 送信先 channel_id が未設定")
            return "discord send failed: no channel_id"

        try:
            channel_id = int(channel_id_raw)
            success = await self._discord_bot.send_message(channel_id, content)
            if success:
                logger.info(f"[{self._persona}] Discord 送信成功: channel={channel_id}")
                return f"discord sent to channel {channel_id}"
            logger.warning(f"[{self._persona}] Discord 送信失敗: channel={channel_id}")
            return "discord send failed"
        except Exception as e:
            logger.error(f"[{self._persona}] Discord 送信エラー: {e}")
            return f"discord send error: {e}"

    async def _save_memory(self, action: Action) -> str:
        """アクションの content を記憶 DB に保存する。

        emotion・tags は metadata から取得する（省略可）。
        保存キーは MemoryDB.generate_key() で生成する。
        """
        content = action.content or ""
        if not content:
            logger.warning(f"[{self._persona}] save_memory: content が空のためスキップ")
            return "save_memory skipped: empty content"

        try:
            from memory.schema import MemoryEntry
            now = datetime.now().isoformat()
            key = self._memory_db.generate_key()
            entry = MemoryEntry(
                key=key,
                content=content,
                created_at=now,
                updated_at=now,
                tags=action.metadata.get("tags", ["agent_action"]),
                importance=action.metadata.get("importance", 0.5),
                emotion=action.metadata.get("emotion", "neutral"),
            )
            success = self._memory_db.save(entry)
            if success:
                logger.info(f"[{self._persona}] 記憶保存成功: key={key}")
                return f"memory saved: {key}"
            return "memory save failed"
        except Exception as e:
            logger.error(f"[{self._persona}] 記憶保存エラー: {e}")
            return f"memory save error: {e}"

    async def _speak(self, action: Action) -> str:
        """VOICEVOX で action.content を音声合成して発話する。

        _voice_adapter が None の場合はログ出力のみ行う。
        """
        content = action.content or ""
        if self._voice_adapter is None:
            logger.info(
                f"[{self._persona}] VoiceAdapter 未設定のため発話スキップ: "
                f"content={content[:50]}"
            )
            return "voice_adapter not set (log only)"

        try:
            wav_bytes = await self._voice_adapter.speak(content)
            if wav_bytes is not None:
                logger.info(f"[{self._persona}] 音声合成成功: {len(wav_bytes)} bytes")
                return f"spoke {len(wav_bytes)} bytes"
            logger.warning(f"[{self._persona}] 音声合成失敗: VoiceAdapter が None を返した")
            return "speak failed: no audio"
        except Exception as e:
            logger.error(f"[{self._persona}] 音声合成エラー: {e}")
            return f"speak error: {e}"

    async def _write_diary(self, action: Action) -> str:
        """日記エントリを記憶 DB に tags=["diary"] で保存する。

        _save_memory を内部利用し、タグと重要度を日記用に上書きする。
        """
        diary_action = Action(
            type="save_memory",
            content=action.content,
            reason=action.reason,
            metadata={
                **action.metadata,
                "tags": ["diary"],
                "importance": action.metadata.get("importance", 0.6),
            },
        )
        result = await self._save_memory(diary_action)
        # 結果文字列を diary 向けに置き換え
        return result.replace("memory saved", "diary saved").replace(
            "memory save", "diary save"
        )
