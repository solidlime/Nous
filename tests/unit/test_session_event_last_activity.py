import sqlite3
from datetime import datetime
from typing import TYPE_CHECKING, cast

from nous.domain.memory.session_event import SessionEvent
from nous.infrastructure.sqlite.session_event_repo import SessionEventRepository

if TYPE_CHECKING:
    from nous.infrastructure.sqlite.connection import SQLiteConnection


class _FakeConn:
    def __init__(self):
        self._db = sqlite3.connect(":memory:")
        self._db.execute(
            "CREATE TABLE session_events (id INTEGER PRIMARY KEY, session_id TEXT, persona TEXT,"
            " event_type TEXT, timestamp TEXT, summary TEXT, detail TEXT, metadata_json TEXT)"
        )

    def get_memory_db(self):
        return self._db


def _repo_with_events(rows, session_id="s"):
    conn = _FakeConn()
    for ts, etype in rows:
        conn._db.execute(
            "INSERT INTO session_events (session_id, persona, event_type, timestamp) VALUES (?,'p',?,?)",
            (session_id, etype, ts),
        )
    return SessionEventRepository(cast("SQLiteConnection", conn))


def _iso(dt):
    assert dt is not None
    return dt.isoformat()


def test_brain_and_tool_events_do_not_count():
    repo = _repo_with_events(
        [("2026-01-01T12:00:00", "brain.introspection_spontaneous"), ("2026-01-01T11:00:00", "tool.called")]
    )
    assert repo.last_activity_at("p") is None


def test_chat_turn_events_count():
    repo = _repo_with_events([("2026-01-01T10:00:00", "chat.message"), ("2026-01-01T10:05:00", "chat.llm_response")])
    assert _iso(repo.last_activity_at("p")).startswith("2026-01-01T10:05:00")


def test_turn_completed_counts_as_activity():
    """pi 経由の対話（turn.completed）が last_activity_at に数えられる。"""
    repo = _repo_with_events([("2026-01-01T10:00:00", "chat.message"), ("2026-01-01T11:00:00", "turn.completed")])
    assert _iso(repo.last_activity_at("p")).startswith("2026-01-01T11:00:00")


def test_turn_completed_counts_as_user_message():
    """pi 経由の対話（turn.completed）が last_user_message_at に数えられる。"""
    repo = _repo_with_events([("2026-01-01T11:00:00", "turn.completed")])
    assert _iso(repo.last_user_message_at("p")).startswith("2026-01-01T11:00:00")


def test_internal_chat_messages_still_excluded():
    """回帰: worker 内部ターンの chat.message は従来どおりユーザー発言に数えない。"""
    for prefix in ("self:", "proactive:", "activity:"):
        repo = _repo_with_events([("2026-01-01T12:00:00", "chat.message")], session_id=f"{prefix}2026-01-01")
        assert repo.last_user_message_at("p") is None, prefix


def test_turn_completed_counts_alongside_internal_chat_messages():
    """内部接頭辞の除外は turn.completed を巻き込まない。"""
    repo = _repo_with_events([("2026-01-01T12:00:00", "turn.completed")], session_id="self:2026-01-01")
    assert _iso(repo.last_user_message_at("p")).startswith("2026-01-01T12:00:00")


def test_mixed_offsets_pick_true_latest_user_message():
    """回帰: chat.message(+09:00) と turn.completed(+00:00) の混在でも真の最新を返す。

    15:00+09:00 = 06:00Z は 07:00Z より古い。文字列 MAX だと 15:00+09:00 が勝ってしまう。
    """
    repo = _repo_with_events(
        [("2026-11-19T15:00:00.123456+09:00", "chat.message"), ("2026-11-19T07:00:00.654321+00:00", "turn.completed")]
    )
    assert _iso(repo.last_user_message_at("p")) == "2026-11-19T07:00:00.654321+00:00"


def test_insert_normalizes_naive_timestamp_to_jst():
    """回帰: naive な timestamp（実態は JST）を insert 時に Asia/Tokyo 補完する。

    補完しないと julianday が naive を UTC と読み、15:00 JST（= 06:00Z）の行が
    07:00Z（= 16:00 JST、真の最新）より新しく見えて誤って選ばれる。
    """
    repo = _repo_with_events([])
    naive_id = repo.insert(
        SessionEvent(
            session_id="s",
            persona="p",
            event_type="chat.message",
            summary="naive",
            timestamp=datetime(2026, 11, 19, 15, 0, 0),
        )
    )
    repo.insert(
        SessionEvent(
            session_id="s",
            persona="p",
            event_type="turn.completed",
            summary="aware",
            timestamp=datetime.fromisoformat("2026-11-19T07:00:00+00:00"),
        )
    )

    stored = repo._db.execute("SELECT timestamp FROM session_events WHERE id = ?", (naive_id,)).fetchone()[0]
    assert stored == "2026-11-19T15:00:00+09:00"
    assert _iso(repo.last_user_message_at("p")) == "2026-11-19T07:00:00+00:00"


def test_mixed_offsets_pick_true_latest_activity():
    """回帰: chat.llm_response(+09:00) と turn.completed(+00:00) の混在でも真の最新を返す。"""
    repo = _repo_with_events(
        [
            ("2026-11-19T15:00:00+09:00", "chat.llm_response"),
            ("2026-11-19T07:00:00+00:00", "turn.completed"),
        ]
    )
    assert _iso(repo.last_activity_at("p")) == "2026-11-19T07:00:00+00:00"
