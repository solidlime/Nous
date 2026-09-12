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

    asyncio.run(
        mod._summarize_and_record(
            ctx, engine, "p", "気になること", [{"tool_name": "web_search", "args": {}, "result": "データ"}]
        )
    )
    mono = [e for e in events if getattr(e, "event_type", "") == "brain.monologue"]
    assert mono and mono[0].summary.startswith("調べたら")


def test_summarize_falls_back_to_raw_text_on_non_json():
    """非JSON応答は無言廃棄せず生テキストを要約として採用する (旧実装の挙動復活)。"""
    from nous.application.chat import introspection as mod

    ctx = MagicMock()
    ctx._session_event_repo = None
    created = []

    async def _create(**kwargs):
        created.append(kwargs)
        return MagicMock()

    ctx.memory_service = MagicMock()
    ctx.memory_service.create_memory = _create

    engine = MagicMock()
    _fake_llm(engine, "調べたら雲は500トンだった。")
    asyncio.run(
        mod._summarize_and_record(
            ctx, engine, "p", "気になること", [{"tool_name": "web_search", "args": {}, "result": "データ"}]
        )
    )
    assert created and created[0]["content"] == "調べたら雲は500トンだった。"
    assert created[0]["tags"] == ["exploration", "introspection"]


def _async_ok():
    async def _ok(*a, **k):
        return MagicMock()

    return _ok


def _fake_llm(engine, payload):
    async def _llm(prompt):
        return payload, None

    engine._call_llm = _llm
    return engine
