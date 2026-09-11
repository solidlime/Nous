import asyncio
from unittest.mock import MagicMock


def test_summarize_persists_brain_monologue_event(monkeypatch):
    from nous.application.chat import introspection as mod

    ctx = MagicMock()
    ctx._session_event_repo = MagicMock()
    ctx.memory_service = MagicMock()
    ctx.memory_service.create_memory = _async_ok()
    events = []
    ctx._session_event_repo.insert = lambda ev: events.append(ev)

    engine = MagicMock()
    _fake_llm(engine, '{"summary": "調べたら面白かった。", "satisfied": true, "unresolved": null}')

    asyncio.run(mod._summarize_and_record(ctx, engine, "p", "気になること", "web_search", {"result": "データ"}))
    mono = [e for e in events if getattr(e, "event_type", "") == "brain.monologue"]
    assert mono and mono[0].summary.startswith("調べたら")


def _async_ok():
    async def _ok(*a, **k):
        return MagicMock()

    return _ok


def _fake_llm(engine, payload):
    async def _llm(prompt):
        return payload, None

    engine._call_llm = _llm
    return engine
