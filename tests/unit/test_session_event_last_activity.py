import sqlite3

from nous.infrastructure.sqlite.session_event_repo import SessionEventRepository


class _FakeConn:
    def __init__(self):
        self._db = sqlite3.connect(":memory:")
        self._db.execute(
            "CREATE TABLE session_events (id INTEGER PRIMARY KEY, session_id TEXT, persona TEXT,"
            " event_type TEXT, timestamp TEXT, summary TEXT, detail TEXT, metadata_json TEXT)"
        )

    def get_memory_db(self):
        return self._db


def _repo_with_events(rows):
    conn = _FakeConn()
    for ts, etype in rows:
        conn._db.execute(
            "INSERT INTO session_events (session_id, persona, event_type, timestamp) VALUES ('s','p',?,?)",
            (etype, ts),
        )
    return SessionEventRepository(conn)


def test_brain_and_tool_events_do_not_count():
    repo = _repo_with_events(
        [("2026-01-01T12:00:00", "brain.introspection_spontaneous"), ("2026-01-01T11:00:00", "tool.called")]
    )
    assert repo.last_activity_at("p") is None


def test_chat_turn_events_count():
    repo = _repo_with_events(
        [("2026-01-01T10:00:00", "chat.message"), ("2026-01-01T10:05:00", "chat.llm_response")]
    )
    assert repo.last_activity_at("p").isoformat().startswith("2026-01-01T10:05:00")
