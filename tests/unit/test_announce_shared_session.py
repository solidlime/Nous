"""自発発言が main 履歴の同じ窓に書くこと（kanban #66）の回帰テスト。"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from nous.application.chat import service
from nous.application.chat.session_manager import SessionManager
from nous.application.workers import announce

PERSONA = "test"


@pytest.fixture(autouse=True)
def fresh_manager(monkeypatch):
    """プロセス共有のマネージャをテスト毎に空にする（他テストの窓を持ち越さない）。"""
    monkeypatch.setattr(service, "_session_manager", SessionManager())


def test_speak_to_main_shares_session_manager(sqlite_conn, monkeypatch) -> None:
    ctx = MagicMock()
    ctx.persona = PERSONA
    ctx.connection = sqlite_conn

    announce.speak_to_main(ctx, "おはよう", max_messages=50)

    # 共有マネージャから見える = 別インスタンスを作っていない
    shared = service.get_session_manager().get_or_create(
        PERSONA, "main", max_messages=50, db=sqlite_conn.get_memory_db()
    )
    assert [m["content"] for m in shared.get_active_path()] == ["おはよう"]


def test_speak_to_main_does_not_drop_live_turn_context(sqlite_conn) -> None:
    """ライブターンが握っている窓に追記され、次回ロードでも両方残る。"""
    ctx = MagicMock()
    ctx.persona = PERSONA
    ctx.connection = sqlite_conn

    live = service.get_session_manager().get_or_create(PERSONA, "main", max_messages=50, db=sqlite_conn.get_memory_db())
    live.add("user", "聞いてる？")

    announce.speak_to_main(ctx, "聞いてるよ", max_messages=50)

    assert [m["content"] for m in live.get_active_path()] == ["聞いてる？", "聞いてるよ"]
    # SQLite にも両方書かれている（片方の窓が丸ごと上書きしていない）
    reloaded = SessionManager().get_or_create(PERSONA, "main", max_messages=50, db=sqlite_conn.get_memory_db())
    assert [m["content"] for m in reloaded.get_active_path()] == ["聞いてる？", "聞いてるよ"]


def test_speak_to_main_from_another_thread_persists(sqlite_conn) -> None:
    """ワーカースレッドから呼んでも chat_sessions に残る（kanban #86）。

    窓の sqlite 接続は生成スレッドに縛られる。ここではサーバーループ役の
    スレッド（＝テストスレッド）で先に窓を作り、別スレッドから
    ``speak_to_main`` を呼ぶ。マーシャルしないと ``ProgrammingError`` を
    ``_persist`` が飲み、発言が DB から消える。
    """
    import asyncio
    import threading

    ctx = MagicMock()
    ctx.persona = PERSONA
    ctx.connection = sqlite_conn
    errors: list[BaseException] = []

    async def _server() -> None:
        service.get_session_manager().bind_loop(asyncio.get_running_loop())
        service.get_session_manager().get_or_create(PERSONA, "main", max_messages=50, db=sqlite_conn.get_memory_db())

        def _worker() -> None:
            try:
                announce.speak_to_main(ctx, "別スレッドから", max_messages=50)
            except BaseException as e:  # pragma: no cover - 失敗時のみ
                errors.append(e)

        thread = threading.Thread(target=_worker)
        thread.start()
        while thread.is_alive():
            await asyncio.sleep(0.01)
        thread.join()

    asyncio.run(_server())
    assert errors == []

    reloaded = SessionManager().get_or_create(PERSONA, "main", max_messages=50, db=sqlite_conn.get_memory_db())
    assert [m["content"] for m in reloaded.get_active_path()] == ["別スレッドから"]


def test_speak_to_main_records_ref_without_leaking_it_into_the_text(sqlite_conn) -> None:
    """相関子（kanban #69）は session event にだけ載せ、本文には混ぜない。"""
    from nous.infrastructure.sqlite.session_event_repo import SessionEventRepository

    ctx = MagicMock()
    ctx.persona = PERSONA
    ctx.connection = sqlite_conn

    announce.speak_to_main(ctx, "日記を書いたよ", max_messages=50, event_type="agent.task.spoke", ref="task=mem_1")

    window = service.get_session_manager().get_or_create(
        PERSONA, "main", max_messages=50, db=sqlite_conn.get_memory_db()
    )
    assert [m["content"] for m in window.get_active_path()] == ["日記を書いたよ"]

    event = SessionEventRepository(sqlite_conn).get_by_persona(PERSONA, limit=5)[0]
    assert event.event_type == "agent.task.spoke"
    assert event.summary == "task=mem_1 日記を書いたよ"
