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
