"""SessionWindow + SessionManager: チャット会話ウィンドウ管理 + SQLite永続化。

各クラスは分割モジュールから再エクスポート:
  - session_window  → SessionWindow, _expand_segments
  - tree_session    → TreeSessionWindow
  - session_manager → SessionManager, _CHAT_SESSIONS_SCHEMA, _cleanup_expired_sessions
"""

from .session_manager import (  # noqa: F401
    _CHAT_SESSIONS_SCHEMA,
    SessionManager,
    _cleanup_expired_sessions,
)
from .session_window import _expand_segments  # noqa: F401
from .tree_session import TreeSessionWindow

# 後方互換エイリアス: SessionWindow → TreeSessionWindow
SessionWindow = TreeSessionWindow  # noqa: A001 — backward compat
