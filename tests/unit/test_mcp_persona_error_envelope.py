"""v4.0.1 — persona resolution failures come back as the C1 envelope.

Before: ``X-Persona: <unknown>`` → ``AppContextRegistry.get()`` raises → the SDK
wraps it in ``UnexpectedToolError`` → the client got "Error executing tool <name>"
with no ``error.code``. Now ``Tool.run()`` (patched in ``nous.main``) maps the
typed persona errors to the same ``{ok, data, error}`` envelope every other tool
failure uses.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import TextContent

from nous.api.mcp.middleware import _persona_var
from nous.api.mcp.tools import register_tools
from nous.application.use_cases import AppContextRegistry
from nous.main import MemoryFastMCP  # noqa: F401 — import applies the Tool.run patch


@pytest.fixture
def empty_persona_root(tmp_path, monkeypatch):
    """Registry pointed at an empty persona dir (class state restored after)."""
    settings = MagicMock()
    settings.persona_dir = str(tmp_path)
    monkeypatch.setattr(AppContextRegistry, "_settings", settings)
    monkeypatch.setattr(AppContextRegistry, "_contexts", {})
    return tmp_path


@pytest.fixture
def server() -> MemoryFastMCP:
    mcp = MemoryFastMCP("test")
    register_tools(mcp)
    return mcp


async def _call_with_persona(mcp: MemoryFastMCP, persona: str) -> dict:
    token = _persona_var.set(persona)
    try:
        result = await mcp.call_tool("session_begin", {})
    finally:
        _persona_var.reset(token)
    blocks = getattr(result, "content", None)
    assert blocks, f"no content on {result!r}"
    block = blocks[0]
    assert isinstance(block, TextContent), f"unexpected block {block!r}"
    payload: dict = json.loads(block.text)
    return payload


@pytest.mark.asyncio
async def test_unknown_persona_returns_not_found_envelope(server, empty_persona_root):
    payload = await _call_with_persona(server, "ghost")

    assert payload["ok"] is False
    assert payload["data"] is None
    assert payload["error"]["code"] == "NOT_FOUND"
    assert "ghost" in payload["error"]["message"]


@pytest.mark.asyncio
async def test_traversal_persona_returns_validation_envelope(server, empty_persona_root):
    payload = await _call_with_persona(server, "../etc")

    assert payload["ok"] is False
    assert payload["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_unrelated_crash_is_not_enveloped(empty_persona_root):
    """The mapping is keyed on the typed persona errors, not on ValueError text."""
    mcp = MemoryFastMCP("test")

    @mcp.tool()
    async def boom() -> str:
        raise ValueError("Persona 'x' not found")  # look-alike message

    with pytest.raises(ToolError):
        await mcp.call_tool("boom", {})
