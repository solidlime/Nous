"""自発発言を main 履歴 + SSE で届ける共有経路（kanban #65）。

``ProactiveWorker`` の「話しかける」と ``ProspectiveWorker`` の「予定を実行した
報告」は同じ形で届く（``turn_started`` → ``text_delta`` → ``done``、フロントは
``send/turn.js`` の受信と同じ扱いをする）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from nous.application.chat.events import DoneSSE, TextDeltaSSE
from nous.application.chat.service import get_session_manager, get_turn_hub
from nous.domain.memory.session_event import SessionEvent
from nous.domain.shared.time_utils import get_now
from nous.infrastructure.logging.structured import get_logger
from nous.infrastructure.sqlite.session_event_repo import SessionEventRepository

if TYPE_CHECKING:
    from nous.application.use_cases import AppContext

logger = get_logger(__name__)

#: 自発発言の既定イベント種別（ProactiveWorker が cooldown 判定に使う）。
SPOKE_EVENT = "proactive.spoke"


def speak_to_main(
    ctx: AppContext,
    text: str,
    max_messages: int,
    event_type: str = SPOKE_EVENT,
) -> None:
    """main 履歴へ追記し、既存 chat() と同じ形の SSE で届ける。"""
    # ワーカースレッドから呼ばれるので、sqlite 接続は追記するスレッドで作る
    # （db_factory はマーシャル先のループで解決される。kanban #86）。
    get_session_manager().append(
        ctx.persona,
        "main",
        "assistant",
        text,
        max_messages=max_messages,
        db_factory=ctx.connection.get_memory_db,
    )

    hub = get_turn_hub()
    # フロントは turn_started でターン枠を開き、text_delta を本文として描き、
    # done で確定してから履歴を取り直す（send/turn.js）。user_message は
    # 空（自発発言にユーザーの発話は無い）。
    hub.publish_synthetic(ctx.persona, {"type": "turn_started", "user_message": "", "session_id": "main"})
    hub.publish(ctx.persona, TextDeltaSSE(content=text).to_sse())
    hub.publish(ctx.persona, DoneSSE().to_sse())

    try:
        SessionEventRepository(ctx.connection).insert(
            SessionEvent(
                session_id="main",
                persona=ctx.persona,
                event_type=event_type,
                timestamp=get_now(),
                summary=text[:200],
            )
        )
    except Exception:
        logger.debug("speak_to_main: failed to record %s", event_type, exc_info=True)
    logger.info("speak_to_main: persona=%s %s %s", ctx.persona, event_type, text[:60])
