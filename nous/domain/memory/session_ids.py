"""worker が内部で回すターンのセッション ID 規約（kanban #65）。

``self:`` / ``proactive:`` / ``activity:`` はアシスタント自身が回すターンで、
ユーザーの発話ではない。この接頭辞を「ユーザー発言」として数えると
idle タイマーを自分でリセットする自己ループになる。

接頭辞をここに集約する理由: 以前は ``session_event_repo`` と各 worker に
リテラルが散っていて、``activity:`` だけ抜け落ちた。
"""

from __future__ import annotations

#: 予定の自走ターン（``schedule.run_self_turn``）。
SELF_SESSION_PREFIX = "self:"
#: 自発発言の判定ターン（``ProactiveWorker``）。
PROACTIVE_SESSION_PREFIX = "proactive:"
#: 自発活動のターン（``ActivityWorker``）。
ACTIVITY_SESSION_PREFIX = "activity:"

#: ユーザーの発話ではない内部ターンのセッション ID 接頭辞。
INTERNAL_SESSION_PREFIXES: tuple[str, ...] = (
    SELF_SESSION_PREFIX,
    PROACTIVE_SESSION_PREFIX,
    ACTIVITY_SESSION_PREFIX,
)


def is_internal_session(session_id: str) -> bool:
    """内部ターンのセッション ID かどうか。"""
    return session_id.startswith(INTERNAL_SESSION_PREFIXES)
