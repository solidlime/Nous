"""tool.called → chat SSE hub forwarding (spec C).

内省 curiosity 探索の tool.called は event_bus に publish されるだけでは
``/api/chat/{persona}/events`` (TurnHub) に届かない。AppContext の転送購読が
名前付き SSE イベントとして hub に流すことを検証する。
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from nous.api.mcp._tools_helpers import _emit_tool_called
from nous.application.chat.turn_hub import TurnHub


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
