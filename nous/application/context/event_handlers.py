"""Event subscription handlers（責務5の非ベクトル系）.

AppContext（composition root の facade）が継承する mixin。
tool.called → chat SSE hub 転送 / tool.called → 対話活動時間の記録 /
セッション内メモリ co-access 追跡（Hebbian リンク用）の実装本体を担う。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nous.domain.persona.service import PersonaService

logger = logging.getLogger(__name__)


class EventHandlersMixin:
    """イベント購読ハンドラとセッション内追跡の実装（責務5のうちベクトル系以外）。"""

    if TYPE_CHECKING:
        # ホスト（AppContext）が提供する属性の型宣言（mixin 公式パターン）。
        persona: str
        persona_service: PersonaService
        _introspection_tool_active: bool
        _coaccess_keys: list[str]

    def _init_volatile_state(self) -> None:
        """セッション内 volatile 状態の初期化（curiosity フラグと co-access 追跡）。"""
        # 内省 curiosity サイクル中フラグ（hub 経由の自サーバー tool.called 抑制用）
        self._introspection_tool_active = False
        # In-memory Hebbian co-access tracker: keys of memories read/created
        # in this session (rolling window, most recent last).  Volatile by
        # design — Hebbian links rebuild progressively, so nothing is lost.
        self._coaccess_keys: list[str] = []

    def record_memory_access(self, key: str) -> None:
        """Record a memory key in the Hebbian co-access tracker.

        Rolling window of the last 20 keys (most recent last); duplicates are
        moved to the end so repeated reads keep recency.  Best-effort: never
        raises into the caller (MCP tool flow).
        """
        if not key:
            return
        try:
            if key in self._coaccess_keys:
                self._coaccess_keys.remove(key)
            self._coaccess_keys.append(key)
            del self._coaccess_keys[:-20]
        except Exception:
            logger.debug("record_memory_access failed for %s", key, exc_info=True)

    async def _on_tool_called_to_hub(self, event_type: str, data: dict) -> None:
        """Forward ``tool.called`` to this persona's chat SSE hub (best-effort).

        The chat log listens on ``/api/chat/{persona}/events`` (a TurnHub, fed
        by turn-scoped events) — event_bus events never reach it. 内省 curiosity
        探索の tool.called を live 表示するため hub へ名前付きイベントで転送する
        (spec C)。persona はイベントが持つ値を優先し、無ければこのコンテキストの
        persona を使う（EventBus は persona 毎に1つ）。
        """
        try:
            persona = data.get("persona") or getattr(self, "persona", None)
            if not persona:
                return
            from nous.application.chat.service import get_turn_hub

            get_turn_hub().publish_event(persona, "tool_called", data)
        except Exception:
            import logging as _logging

            _logging.getLogger("nous").debug("tool.called→hub forward failed", exc_info=True)

    async def _on_tool_called_record_conversation(self, event_type: str, data: dict) -> None:
        """tool.called をユーザー由来の対話活動として last_conversation_time に記録する。

        内省由来は除外: (1) _emit_tool_called の source="introspection" タグ、
        (2) curiosity サイクル中フラグ — hub 経由で自サーバーのツールを叩いた場合は
        サーバー側 publish に source が付かないためフラグで握り潰す。
        内省は一人で動くサイクルでユーザーの介入が無い前提の製品方針。
        """
        try:
            if data.get("source") == "introspection":
                return
            if getattr(self, "_introspection_tool_active", False):
                return
            persona = data.get("persona")
            if not isinstance(persona, str) or not persona:
                return
            self.persona_service.record_conversation_time(persona)
        except Exception:
            import logging as _logging

            _logging.getLogger("nous").debug("tool.called→conversation_time record failed", exc_info=True)
