import sqlite3
from datetime import datetime, timedelta
from types import SimpleNamespace

from nous.application.workers.enrichment_worker import EnrichmentWorker
from nous.infrastructure.sqlite.session_event_repo import SessionEventRepository


class _FakeConn:
    def __init__(self):
        self._db = sqlite3.connect(":memory:")
        self._db.row_factory = sqlite3.Row
        self._db.execute(
            "CREATE TABLE session_events (id INTEGER PRIMARY KEY, session_id TEXT, persona TEXT,"
            " event_type TEXT, timestamp TEXT, summary TEXT, detail TEXT, metadata_json TEXT)"
        )

    def get_memory_db(self):
        return self._db


def _repo(rows):
    conn = _FakeConn()
    for etype, ts in rows:
        conn._db.execute(
            "INSERT INTO session_events (session_id, persona, event_type, timestamp) VALUES ('s','p',?,?)",
            (etype, ts.isoformat()),
        )
    return SessionEventRepository(conn)


def _worker(repo, now, interval_hours=1):
    w = EnrichmentWorker.__new__(EnrichmentWorker)
    w._persona = "p"
    w.context = SimpleNamespace(introspection_engine=object(), _session_event_repo=repo)
    w._config = SimpleNamespace(
        brain_spontaneous_enabled=True, brain_spontaneous_interval_hours=interval_hours
    )
    w._now = lambda: now
    return w


def _fire(w, monkeypatch, calls):
    from nous.application.chat import introspection as mod

    async def fake_run(*a, **k):
        calls.append(a)

    monkeypatch.setattr(mod, "run_spontaneous", fake_run)
    w._maybe_spontaneous(idle_seconds=9999)


def test_turn_introspection_does_not_block_spontaneous(monkeypatch):
    """spontaneous 1h前 + ターン内省 5m前 → spontaneous クロックのみ参照し発火する。"""
    now = datetime(2026, 1, 1, 12, 0, 0)
    repo = _repo(
        [
            ("brain.introspection", now - timedelta(minutes=5)),
            ("brain.introspection_spontaneous", now - timedelta(hours=2)),
        ]
    )
    calls = []
    _fire(_worker(repo, now), monkeypatch, calls)
    assert calls


def test_recent_spontaneous_blocks(monkeypatch):
    """spontaneous が interval 内なら発火しない。"""
    now = datetime(2026, 1, 1, 12, 0, 0)
    repo = _repo([("brain.introspection_spontaneous", now - timedelta(minutes=30))])
    calls = []
    _fire(_worker(repo, now), monkeypatch, calls)
    assert not calls


def test_no_history_fires(monkeypatch):
    """履歴なしは発火する。"""
    now = datetime(2026, 1, 1, 12, 0, 0)
    calls = []
    _fire(_worker(_repo([]), now), monkeypatch, calls)
    assert calls
