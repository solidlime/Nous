"""tool.called → chat SSE hub forwarding (spec C).

内省 curiosity 探索の tool.called は event_bus に publish されるだけでは
``/api/chat/{persona}/events`` (TurnHub) に届かない。AppContext の転送購読が
名前付き SSE イベントとして hub に流すことを検証する。
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from types import SimpleNamespace

from nous.api.mcp._tools_helpers import _emit_tool_called
from nous.application.chat.turn_hub import TurnHub
from nous.application.event_bus import EventBus
from nous.application.session_event_recorder import SessionEventRecorder
from nous.infrastructure.sqlite.session_event_repo import SessionEventRepository


class _Bus:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    async def publish(self, event_type, data):
        self.events.append((event_type, data))


def test_emit_tool_called_includes_persona_and_source():
    ctx = SimpleNamespace(event_bus=_Bus(), session_id="s1")
    asyncio.run(_emit_tool_called(ctx, "web_search", "result", True, persona="herta", source="introspection"))
    event_type, data = ctx.event_bus.events[0]
    assert event_type == "tool.called"
    assert data["persona"] == "herta"
    assert data["source"] == "introspection"
    assert data["tool_name"] == "web_search"


def test_emit_tool_called_backward_compat_omits_persona():
    ctx = SimpleNamespace(event_bus=_Bus(), session_id=None)
    asyncio.run(_emit_tool_called(ctx, "memory_read", "ok", True))
    _t, data = ctx.event_bus.events[0]
    assert "persona" not in data
    assert data["source"] == "direct"


def test_emit_tool_called_session_id_override_and_ellipsis():
    ctx = SimpleNamespace(event_bus=_Bus(), session_id=None)
    asyncio.run(_emit_tool_called(ctx, "mcp-hub__search_tools", "x" * 200, True, session_id="introspection"))
    _t, data = ctx.event_bus.events[0]
    assert data["session_id"] == "introspection"
    assert len(data["result_summary"]) == 80
    assert data["result_summary"].endswith("…")


def test_emit_tool_called_sets_metadata_source_for_both_sources():
    for source in ("direct", "introspection"):
        ctx = SimpleNamespace(event_bus=_Bus(), session_id="s")
        asyncio.run(_emit_tool_called(ctx, "t", "r", True, source=source))
        _t, data = ctx.event_bus.events[0]
        assert data["source"] == source  # front のライブフィルタ用
        assert data["metadata"]["source"] == source  # recorder 永続用


class _MemConn:
    def __init__(self) -> None:
        self._db = sqlite3.connect(":memory:")
        self._db.execute(
            "CREATE TABLE session_events (id INTEGER PRIMARY KEY, session_id TEXT, persona TEXT,"
            " event_type TEXT, timestamp TEXT, summary TEXT, detail TEXT, metadata_json TEXT)"
        )

    def get_memory_db(self):
        return self._db


def test_recorder_persists_source_in_metadata_json():
    conn = _MemConn()
    repo = SessionEventRepository(conn)
    bus = EventBus()
    SessionEventRecorder(bus, repo).start()
    ctx = SimpleNamespace(event_bus=bus, session_id="s1", persona="herta")

    asyncio.run(
        _emit_tool_called(
            ctx, "web_search", "r", True, source="introspection", session_id="introspection", persona="herta"
        )
    )

    row = conn.get_memory_db().execute("SELECT persona, session_id, metadata_json FROM session_events").fetchone()
    assert row is not None
    assert row[0] == "herta"
    assert row[1] == "introspection"
    assert json.loads(row[2])["source"] == "introspection"


def test_turn_hub_publish_event_emits_named_sse():
    async def _run():
        hub = TurnHub()
        q = hub.subscribe("herta")
        hub.publish_event("herta", "tool_called", {"tool_name": "web_search", "source": "introspection"})
        return q.get_nowait(), hub.snapshot_after("herta", 0)

    (seq, sse), buffered = asyncio.run(_run())
    assert sse.startswith("event: tool_called\ndata: ")
    assert sse.endswith("\n\n")
    assert '"source": "introspection"' in sse
    assert buffered == [(seq, sse)]


def test_appcontext_forwards_tool_called_to_hub():
    import nous.application.chat.service as svc
    from nous.application.use_cases import AppContext

    async def _run():
        hub = TurnHub()
        original = svc._turn_hub
        svc._turn_hub = hub
        try:
            q = hub.subscribe("herta")
            ctx = SimpleNamespace(persona="herta")
            await AppContext._on_tool_called_to_hub(
                ctx,
                "tool.called",
                {"tool_name": "web_search", "source": "introspection", "persona": "herta"},
            )
            return q.get_nowait()
        finally:
            svc._turn_hub = original

    _seq, sse = asyncio.run(_run())
    assert "event: tool_called" in sse
    assert '"tool_name": "web_search"' in sse
