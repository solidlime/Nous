"""
非同期イベントバス。

AgentLoop が外部イベント（Discord メッセージ・Webhook・スケジュール）を
受け取るための優先度付きキューラッパー。

PriorityQueue に格納する AgentEvent は priority フィールドで順序付けされる。
数値が小さいほど高優先度（通常の heapq 最小ヒープ）。
"""

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional


class EventType(Enum):
    """AgentLoop が処理するイベント種別。"""
    DISCORD_MESSAGE = "discord_message"
    WEBHOOK_RECEIVED = "webhook_received"
    SCHEDULE_TRIGGER = "schedule_trigger"
    DRIVE_OVERFLOW = "drive_overflow"
    CONSCIOUSNESS_TICK = "consciousness_tick"
    USER_WEB_MESSAGE = "user_web_message"


@dataclass(order=True)
class AgentEvent:
    """優先度付きイベント。

    priority: 数値が小さいほど先に処理される（外部メッセージ=1, Webhook=2, スケジュール=5）。
    event_type: イベント種別。
    persona: 対象ペルソナ名。
    data: イベント固有のペイロード。
    created_at: イベント生成時刻。
    event_id: 重複排除・追跡用の一意 ID（デフォルトは UUID4 文字列）。
    """
    priority: int
    event_type: EventType = field(compare=False)
    persona: str = field(compare=False)
    data: Dict[str, Any] = field(compare=False, default_factory=dict)
    created_at: datetime = field(compare=False, default_factory=datetime.now)
    event_id: str = field(compare=False, default_factory=lambda: str(uuid.uuid4()))


class EventBus:
    """AgentLoop 用の非同期優先度キュー。

    put() / get() は非同期で、キューが満杯／空の場合はそれぞれ待機する。
    try_get_nowait() はポーリング用のノンブロッキング取得。

    Args:
        maxsize: キューの最大サイズ（デフォルト 100）。満杯時は put() が待機する。
    """

    def __init__(self, maxsize: int = 100) -> None:
        self._queue: asyncio.PriorityQueue[AgentEvent] = asyncio.PriorityQueue(
            maxsize=maxsize
        )

    async def put(self, event: AgentEvent) -> None:
        """イベントをキューに追加する。キューが満杯なら空くまで待機する。"""
        await self._queue.put(event)

    async def get(self) -> AgentEvent:
        """キューからイベントを取り出す。キューが空なら追加されるまで待機する。"""
        return await self._queue.get()

    def try_get_nowait(self) -> Optional[AgentEvent]:
        """ノンブロッキングでイベントを取り出す。キューが空なら None を返す。"""
        try:
            return self._queue.get_nowait()
        except asyncio.QueueEmpty:
            return None

    def qsize(self) -> int:
        """現在キューに入っているイベント数を返す。"""
        return self._queue.qsize()

    def empty(self) -> bool:
        """キューが空かどうかを返す。"""
        return self._queue.empty()
