"""Lifecycle: session_id 状態とシャットダウン（責務4）.

AppContext（composition root の facade）が継承する mixin。
session_id プロパティと close / close_async の実装本体を担う。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import threading

    from nous.infrastructure.qdrant.adapter import QdrantVectorStore
    from nous.infrastructure.sqlite.connection import SQLiteConnection


class LifecycleMixin:
    """セッション状態（session_id）と close 系の実装（責務4）。"""

    if TYPE_CHECKING:
        # ホスト（AppContext）が提供する属性の型宣言（mixin 公式パターン）。
        _current_session_id: str | None
        _vector_store: QdrantVectorStore | None
        _vector_store_ready: threading.Event
        connection: SQLiteConnection

    def _init_lifecycle_state(self) -> None:
        """セッション状態の初期化。"""
        self._current_session_id: str | None = None

    @property
    def session_id(self) -> str | None:
        """Current chat session ID, set by ChatService.chat().

        Used by MCP tools to propagate session context to
        MemoryLinkService for Hebbian co-activation linking.
        """
        return self._current_session_id

    @session_id.setter
    def session_id(self, value: str | None) -> None:
        self._current_session_id = value

    async def close_async(self) -> None:
        """Async close: release Qdrant connection and SQLite connection."""
        if self._vector_store is not None:
            await self._vector_store.client_manager.close()
        self.connection.close()

    def close(self) -> None:
        self.connection.close()
        # Unblock any waiter on an init that will never complete (daemon thread died, etc.)
        self._vector_store_ready.set()
