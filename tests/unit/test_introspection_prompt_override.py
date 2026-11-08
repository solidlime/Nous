from nous.application.chat.introspection import _format_prompt


def test_default_when_empty():
    got = _format_prompt("", "Hello {persona}! {current_state}", persona="H", current_state="cs")
    assert got == "Hello H! cs"


def test_override_used():
    got = _format_prompt("X{persona}X", "Hello {persona}", persona="H", current_state="cs")
    assert got == "XHX"


def test_broken_override_falls_back():
    got = _format_prompt("broken {missing_key}", "Hello {persona}", persona="H", current_state="cs")
    assert got == "Hello H"
