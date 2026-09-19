"""P0 red tests: schema-contract parity gaps from the 2026-09-19 design audit.

Each test pins the DESIRED contract. Strict xfail records the current red state
(audit baseline); each must be flipped to a passing test when its phase lands.

- audit:C2  item_add positional-argument shift (quantity → visual_desc, tags → quantity)
  [FIXED in P1 — test now passes; xfail marker removed]
- audit:M6  memory_delete by query deletes the top-1 hit with no similarity threshold
  [FIXED in P1 (QUERY_RESOLVE_MIN_SCORE=0.3) — test now passes; xfail marker removed]
- audit:M7  memory_create accepts empty content (no required schema, plain-text error)
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

from nous.api.mcp._tools_item import _tool_item_add
from nous.api.mcp._tools_memory import _tool_memory_create, _tool_memory_delete
from nous.domain.shared.result import Success
from tests.parity.conftest import make_search_result


async def test_item_add_passes_quantity_and_tags_by_keyword(mock_app_context):
    ctx = mock_app_context
    ctx.equipment_service.add_item = MagicMock()
    ctx.event_bus.publish = AsyncMock()

    await _tool_item_add(
        ctx, "heruta", item_name="Sword", category="weapon", description="sharp", quantity=2, tags=["rare"]
    )

    kwargs = ctx.equipment_service.add_item.call_args.kwargs
    assert kwargs.get("quantity") == 2
    assert kwargs.get("tags") == ["rare"]
    assert kwargs.get("visual_desc") is None or kwargs.get("visual_desc") == "sharp"


async def test_memory_delete_by_query_requires_similarity_threshold(mock_app_context):
    ctx = mock_app_context
    irrelevant = make_search_result("mem_low", score=0.05)
    ctx.search_engine.search = AsyncMock(return_value=Success([irrelevant]))
    ctx.memory_service.delete_memory = MagicMock(return_value=Success(True))

    await _tool_memory_delete(ctx, "heruta", query="completely unrelated words")

    assert ctx.memory_service.delete_memory.call_count == 0, "deleted a memory with similarity 0.05"


async def test_memory_create_empty_content_returns_validation_envelope(mock_app_context):
    ctx = mock_app_context
    ctx.persona_service.get_state_snapshot = MagicMock(return_value=("neutral", 0.0, {}, None))

    result = await _tool_memory_create(ctx, "heruta", content="")

    try:
        payload = json.loads(result)
    except (json.JSONDecodeError, TypeError):
        payload = {}
    assert payload.get("ok") is False
    assert payload.get("error", {}).get("code") == "VALIDATION_ERROR"
