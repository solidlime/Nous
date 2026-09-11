from nous.application.chat.introspection import IntrospectionEngine, _format_prompt


def test_default_when_empty():
    got = _format_prompt("", "Hello {persona}! {current_state}", persona="H", current_state="cs")
    assert got == "Hello H! cs"


def test_override_used():
    got = _format_prompt("X{persona}X", "Hello {persona}", persona="H", current_state="cs")
    assert got == "XHX"


def test_broken_override_falls_back():
    got = _format_prompt("broken {missing_key}", "Hello {persona}", persona="H", current_state="cs")
    assert got == "Hello H"


def test_generate_spontaneous_uses_override(monkeypatch):
    engine = IntrospectionEngine.__new__(IntrospectionEngine)
    captured = {}

    async def fake_call_llm(user_message):
        captured["msg"] = user_message
        return '{"monologue": "hi"}', None

    monkeypatch.setattr(engine, "_call_llm", fake_call_llm)
    import asyncio

    asyncio.run(
        engine.generate_spontaneous(
            "p", "sys", [], {}, prompt_override="OVERRIDE {persona} {current_state} {memory_texts} {persona_identity}"
        )
    )
    assert captured["msg"].startswith("OVERRIDE")
