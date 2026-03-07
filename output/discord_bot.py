"""
Discord Bot 出力アダプター。

discord.py を使って Discord サーバーに接続する。
受信メッセージ → EventBus への投入（イベント受信）
Discord チャンネルへの送信（アクション実行）
の2方向を担う。
"""

import asyncio
import logging
from typing import Any, Optional

import discord
from discord.ext import commands

logger = logging.getLogger(__name__)


class DiscordBot:
    """discord.py Bot ラッパー。

    AgentLoop にイベントを届ける受信側と、
    AgentLoop の指示でチャンネルにメッセージを送る送信側を両方担う。

    Args:
        persona: ペルソナ名（ログ用）。
        token: Discord Bot トークン。
        agent_loop: AgentLoop インスタンス（メッセージを EventBus に転送するため）。
        config: Nous 設定 dict（allowed_guild_ids 等の参照に使用）。
    """

    def __init__(
        self,
        persona: str,
        token: str,
        agent_loop: Any = None,
        config: Optional[dict] = None,
    ) -> None:
        self._persona = persona
        self._token = token
        self._agent_loop = agent_loop
        self._config = config or {}

        intents = discord.Intents.default()
        intents.message_content = True
        self._bot = commands.Bot(command_prefix="!", intents=intents)
        self._setup_events()

    def _setup_events(self) -> None:
        """Bot イベントハンドラーを登録する。"""

        @self._bot.event
        async def on_ready() -> None:
            logger.info(
                f"Discord Bot 接続完了: {self._bot.user} [{self._persona}]"
            )

        @self._bot.event
        async def on_message(message: discord.Message) -> None:
            # 自分自身のメッセージは無視
            if message.author == self._bot.user:
                return

            # Bot コマンドの処理（"!" prefix）
            await self._bot.process_commands(message)

            # 許可 Guild チェック
            discord_cfg = self._config.get("discord", {})
            allowed_guilds = discord_cfg.get("allowed_guild_ids", [])
            if (
                allowed_guilds
                and message.guild
                and message.guild.id not in [int(g) for g in allowed_guilds]
            ):
                return

            # AgentLoop が存在してかつ EventBus が初期化済みなら投入
            if (
                self._agent_loop is not None
                and getattr(self._agent_loop, "_event_bus", None) is not None
            ):
                from agent.event_bus import AgentEvent, EventType
                event = AgentEvent(
                    priority=1,
                    event_type=EventType.DISCORD_MESSAGE,
                    persona=self._persona,
                    data={
                        "content": message.content,
                        "user_id": str(message.author.id),
                        "username": str(message.author.name),
                        "channel_id": str(message.channel.id),
                        "guild_id": str(message.guild.id) if message.guild else None,
                    },
                )
                try:
                    await self._agent_loop._event_bus.put(event)
                    logger.debug(
                        f"Discord メッセージをイベントバスに投入: "
                        f"{message.author}: {message.content[:50]}"
                    )
                except Exception as e:
                    logger.error(f"イベントバスへの投入失敗: {e}")

    async def send_message(self, channel_id: int, content: str) -> bool:
        """指定チャンネルにメッセージを送信する。

        Args:
            channel_id: 送信先の Discord チャンネル ID。
            content: 送信するテキスト。

        Returns:
            送信成功なら True。
        """
        try:
            channel = self._bot.get_channel(channel_id)
            if channel is None:
                channel = await self._bot.fetch_channel(channel_id)
            await channel.send(content)
            logger.info(
                f"Discord 送信成功: channel={channel_id}, "
                f"content={content[:50]}... [{self._persona}]"
            )
            return True
        except discord.Forbidden:
            logger.warning(
                f"Discord 送信権限なし: channel={channel_id} [{self._persona}]"
            )
            return False
        except Exception as e:
            logger.error(
                f"Discord 送信エラー: channel={channel_id}, error={e} [{self._persona}]"
            )
            return False

    async def start_async(self) -> None:
        """非同期で Bot を起動する。CancelledError は正常終了として扱う。"""
        try:
            await self._bot.start(self._token)
        except asyncio.CancelledError:
            pass
        except discord.LoginFailure:
            logger.error(
                f"Discord Bot ログイン失敗: トークンを確認してください [{self._persona}]"
            )
        except Exception as e:
            logger.error(
                f"Discord Bot 予期しないエラー: {e} [{self._persona}]",
                exc_info=True,
            )

    async def close(self) -> None:
        """Bot の接続を閉じる。"""
        try:
            await self._bot.close()
            logger.info(f"Discord Bot 切断: {self._persona}")
        except Exception as e:
            logger.warning(f"Discord Bot クローズエラー: {e}")
