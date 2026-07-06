from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)

# イベントタイプ定数
EVENT_MEMORY_CREATED = "memory.created"
EVENT_MEMORY_UPDATED = "memory.updated"
EVENT_MEMORY_DELETED = "memory.deleted"
EVENT_CONTEXT_UPDATED = "context.updated"

# Plugin ingestion
EVENT_EVENTS_INGESTED = "events.ingested"

# Chat events
CHAT_MESSAGE = "chat.message"
CHAT_LLM_RESPONSE = "chat.llm_response"
SESSION_STARTED = "session.started"
SESSION_COMPACT = "session.compact"

# Portrait generation
PORTRAIT_GENERATED = "portrait.generated"


class EventBus:
    """イベント購読・発行基盤。pub/subパターン。
    アプリ全体で1インスタンス（AppContextごとに1つ）。"""

    def __init__(self):
        self._subscribers: dict[str, list[Callable[..., Any]]] = {}

    def subscribe(self, event_type: str, handler: Callable[..., Any]):
        """イベントタイプにハンドラを登録。
        handler は async callable: handler(event_type: str, data: dict)
        """
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        self._subscribers[event_type].append(handler)

    def unsubscribe(self, event_type: str, handler: Callable[..., Any]):
        """ハンドラを解除。"""
        if event_type in self._subscribers:
            self._subscribers[event_type] = [h for h in self._subscribers[event_type] if h is not handler]

    async def publish(self, event_type: str, data: dict):
        """イベントを発行。全サブスクライバに非同期通知。
        各ハンドラの例外はログ出力し、後続ハンドラに影響させない。
        """
        handlers = self._subscribers.get(event_type, [])
        for handler in handlers:
            try:
                await handler(event_type, data)
            except Exception as e:
                logger.error("EventBus handler error for %s: %s", event_type, e)

    def subscriber_count(self, event_type: str) -> int:
        """登録ハンドラ数を返す（テスト用）。"""
        return len(self._subscribers.get(event_type, []))
