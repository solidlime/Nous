"""Parity tests for the P2 remainder (audit M8 / L4 / L3)."""

from __future__ import annotations

import inspect
import json
from unittest.mock import AsyncMock, MagicMock, patch

from nous.domain.shared.result import Success


async def test_session_begin_is_registered_and_owns_side_effects():
    """audit M8: session_begin is the canonical session-start entry; it is the
    one that requests the side effects (session_effects=True) from the core."""
    from nous.api.mcp import _tools_persona
    from nous.api.mcp import tools as mcp_tools

    assert "session_begin" in mcp_tools.TOOL_DISPATCH
    assert "get_context" in mcp_tools.TOOL_DISPATCH
    assert mcp_tools.TOOL_DISPATCH["session_begin"] is _tools_persona._tool_session_begin

    with patch("nous.api.mcp._tools_persona._tool_get_context", new=AsyncMock(return_value={"ok": True})) as g:
        await _tools_persona._tool_session_begin(MagicMock(), "p", project="proj")
    assert g.await_args is not None
    assert g.await_args.kwargs["session_effects"] is True
    assert g.await_args.kwargs["project"] == "proj"


def test_get_context_documents_its_deprecation_and_switch():
    """audit M8: get_context keeps v4.x compat effects behind an explicit switch."""
    from nous.api.mcp import _tools_persona

    src = inspect.getsource(_tools_persona._tool_get_context)
    assert "DEPRECATED" in src
    assert "session_effects" in inspect.signature(_tools_persona._tool_get_context).parameters


async def test_item_unequip_on_mcp_surface_rebuilds_appearance():
    """audit L4: item_unequip was HTTP-only; it must exist on MCP too."""
    from nous.api.mcp import _tools_item
    from nous.api.mcp import tools as mcp_tools

    assert "item_unequip" in mcp_tools.TOOL_DISPATCH
    assert mcp_tools.TOOL_DISPATCH["item_unequip"] is _tools_item._tool_item_unequip

    ctx = MagicMock()
    ctx.equipment_service.unequip.return_value = Success(None)
    ctx.equipment_service.get_equipment.return_value = Success({"top": None})
    ctx.event_bus = AsyncMock()

    out = await _tools_item._tool_item_unequip(ctx, "p", slots=["top"])

    assert "Unequipped" in out
    ctx.equipment_service.unequip.assert_called_once_with(["top"])
    # audit C2 — appearance recompute goes through the service (single path)
    ctx.equipment_service.recompute_appearance.assert_called_once()

    async def _no_slots():
        return await _tools_item._tool_item_unequip(ctx, "p", slots=[])

    assert "Error" in await _no_slots()


async def test_extractor_honors_fact_kind():
    """audit L3: the extractor must pass through a valid ``kind`` instead of
    always writing semantic."""
    from nous.application.chat.memory_extractor import _save_extracted_facts

    ctx = MagicMock()
    ctx.search_engine.search = AsyncMock(return_value=Success([]))
    ctx.vector_store = None
    created: list[dict] = []

    async def fake_create(**kwargs):
        created.append(kwargs)
        mem = MagicMock()
        mem.key = "mem_new"
        mem.content = kwargs.get("content", "")
        return Success(mem)

    ctx.memory_service.create_memory = AsyncMock(side_effect=fake_create)

    await _save_extracted_facts(
        ctx,
        "p",
        [
            {"content": "昨日、私は公園で走った", "importance": 0.7, "kind": "episodic"},
            {"content": "私は紅茶が好き", "importance": 0.8, "kind": "semantic"},
            {"content": "私は本を読んでいる", "importance": 0.6, "kind": "bogus"},
        ],
        "",
    )

    kinds = [c.get("kind", "semantic") for c in created]
    assert kinds == ["episodic", "semantic", "semantic"]
    assert json.dumps(created[0], ensure_ascii=False, default=str)
