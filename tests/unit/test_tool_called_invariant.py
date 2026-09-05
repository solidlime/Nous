"""F3 invariant tests: MCP tools self-publish tool.called on ALL paths.

- ToolRegistry must NOT publish for MCP tools (they self-publish)
- ToolRegistry MUST publish for builtin/search_tools
- Audit: every MCP tool function publishes tool.called ≥1 on success AND
  failure paths (parametrized — prevents future tools forgetting to publish)
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from nous.api.mcp._tools_goal import _tool_goal_manage
from nous.api.mcp._tools_item import _tool_item_add, _tool_item_equip, _tool_item_search
from nous.api.mcp._tools_memory import (
    _tool_memory_create,
    _tool_memory_delete,
    _tool_memory_read,
    _tool_memory_search,
    _tool_memory_stats,
    _tool_memory_update,
)
from nous.api.mcp._tools_persona import _tool_get_context, _tool_update_context
from nous.api.mcp._tools_skill import _tool_invoke_skill
from nous.application.chat.tools.registry import SEARCH_TOOLS_NAME, ToolRegistry
from nous.domain.memory.entities import Memory
from nous.domain.search.engine import SearchResult
from nous.domain.shared.errors import RepositoryError
from nous.domain.shared.result import Failure, Success


def _mem(key: str = "mem_001", content: str = "content", tags: list[str] | None = None) -> Memory:
    from datetime import UTC, datetime

    return Memory(key=key, content=content, tags=tags or [], created_at=datetime.now(UTC), updated_at=datetime.now(UTC))


def _tool_called_events(ctx) -> list[dict]:
    """Extract tool.called payloads from the mock event bus."""
    events = []
    for call in ctx.event_bus.publish.call_args_list:
        if call[0][0] == "tool.called":
            events.append(call[0][1])
    return events


def _setup_success_ctx(ctx) -> None:
    """Configure the mock ctx for the success path of every tool."""
    state = SimpleNamespace(
        persona="test_persona",
        emotion="joy",
        emotion_intensity=0.6,
        fatigue=0.2,
        warmth=0.5,
        arousal=0.3,
        heart_rate=0.4,
        pain=0.0,
        action="",
        speech="",
        last_conversation_time=None,
        physical_state="",
        mental_state="",
        environment="",
        relationship_status="",
        persona_info={},
        user_info={},
    )
    ctx.persona_service.get_context.return_value = Success(state)
    ctx.persona_service.get_state_snapshot.return_value = ("neutral", 0.5, {}, "ts")
    ctx.persona_service.get_emotion_history.return_value = Success([])
    ctx.persona_service.update_emotion.return_value = Success(None)
    ctx.memory_service.get_top_by_importance.return_value = Success([])
    ctx.memory_service.get_by_tags.return_value = Success([])
    ctx.memory_service.get_recent.return_value = Success([])
    ctx.memory_service.get_and_consume_one_shot.return_value = Success([])
    ctx.memory_service.get_memory.return_value = Success(_mem())
    ctx.memory_service.create_memory.return_value = Success(_mem("mem_new"))
    ctx.memory_service.update_memory.return_value = Success(_mem())
    ctx.memory_service.delete_memory.return_value = Success(None)
    ctx.memory_service.get_stats.return_value = Success("stats text")
    ctx.memory_service.count_memories.return_value = Success(1)
    ctx.memory_service.log_search.return_value = Success(None)
    ctx.search_engine.search.return_value = Success([SearchResult(memory=_mem(), score=0.9, source="keyword")])
    ctx.equipment_service.get_equipment.return_value = Success({})
    ctx.equipment_service.add_item.return_value = Success(None)
    ctx.equipment_service.equip.return_value = Success(None)
    ctx.equipment_service.build_appearance.return_value = ""
    ctx.equipment_service.search_items.return_value = Success(
        [SimpleNamespace(name="sword", category="weapon", quantity=1)]
    )


# ---------------------------------------------------------------------------
# (a) registry: MCP tools → no publish / (b) builtin → publish
# ---------------------------------------------------------------------------


class TestRegistryPublishInvariant:
    def test_registry_does_not_publish_for_mcp_tools(self, mock_app_context):
        from unittest.mock import AsyncMock

        pool = MagicMock()
        pool.list_all_tools.return_value = []
        pool.call_tool = AsyncMock(return_value={"status": "ok", "content": "done"})
        registry = ToolRegistry(builtin_tools=[], mcp_pool=pool)
        result = asyncio.run(registry.execute(mock_app_context, MagicMock(), "srv__some_tool", {"a": 1}))
        assert result["status"] == "ok"
        assert _tool_called_events(mock_app_context) == [], "registry must not publish for MCP tools"

    def test_registry_publishes_for_search_tools(self, mock_app_context):
        from unittest.mock import AsyncMock

        handler = AsyncMock(return_value={"status": "ok", "content": "[]"})
        registry = ToolRegistry(builtin_tools=[], search_handler=handler)
        result = asyncio.run(registry.execute(mock_app_context, MagicMock(), SEARCH_TOOLS_NAME, {"query": "x"}))
        assert result["status"] == "ok"
        events = _tool_called_events(mock_app_context)
        assert len(events) == 1
        assert events[0]["tool_name"] == SEARCH_TOOLS_NAME
        assert events[0]["success"] is True


# ---------------------------------------------------------------------------
# (c) audit: all 13 MCP tool functions publish on success AND failure
# ---------------------------------------------------------------------------

TOOLS = {
    "get_context": _tool_get_context,
    "memory_create": _tool_memory_create,
    "memory_read": _tool_memory_read,
    "memory_update": _tool_memory_update,
    "memory_delete": _tool_memory_delete,
    "memory_search": _tool_memory_search,
    "memory_stats": _tool_memory_stats,
    "update_context": _tool_update_context,
    "item_add": _tool_item_add,
    "item_equip": _tool_item_equip,
    "item_search": _tool_item_search,
    "goal_manage": _tool_goal_manage,
    "invoke_skill": _tool_invoke_skill,
}

PERSONA = "test_persona"


def _success_call(tool_name: str, ctx):
    """Invoke the tool on its success path. Returns the raw result."""
    if tool_name == "get_context":
        return asyncio.run(_tool_get_context(ctx, PERSONA))
    if tool_name == "memory_create":
        return asyncio.run(_tool_memory_create(ctx, PERSONA, content="hello"))
    if tool_name == "memory_read":
        return asyncio.run(_tool_memory_read(ctx, PERSONA, memory_key="mem_001"))
    if tool_name == "memory_update":
        return asyncio.run(_tool_memory_update(ctx, PERSONA, memory_key="mem_001", content="updated"))
    if tool_name == "memory_delete":
        return asyncio.run(_tool_memory_delete(ctx, PERSONA, memory_key="mem_001"))
    if tool_name == "memory_search":
        return asyncio.run(_tool_memory_search(ctx, PERSONA, query="q"))
    if tool_name == "memory_stats":
        return asyncio.run(_tool_memory_stats(ctx, PERSONA))
    if tool_name == "update_context":
        return asyncio.run(_tool_update_context(ctx, PERSONA, emotion="joy"))
    if tool_name == "item_add":
        return asyncio.run(_tool_item_add(ctx, PERSONA, item_name="sword"))
    if tool_name == "item_equip":
        return asyncio.run(_tool_item_equip(ctx, PERSONA, equipment={"top": "dress"}))
    if tool_name == "item_search":
        return asyncio.run(_tool_item_search(ctx, PERSONA, query="sword"))
    if tool_name == "goal_manage":
        return asyncio.run(_tool_goal_manage(ctx, PERSONA, operation="list"))
    if tool_name == "invoke_skill":
        with patch("nous.domain.skill.SkillRepository.load_from_dir") as load:
            load.return_value = [SimpleNamespace(name="s", content="do things")]
            return asyncio.run(_tool_invoke_skill(ctx, PERSONA, name="s", task="t"))
    raise AssertionError(f"unknown tool: {tool_name}")


def _failure_call(tool_name: str, ctx):
    """Invoke the tool on its failure path (returned failure or exception)."""
    if tool_name == "get_context":
        ctx.persona_service.get_context.return_value = Failure("boom")
        return asyncio.run(_tool_get_context(ctx, PERSONA))
    if tool_name == "memory_create":
        ctx.memory_service.create_memory.return_value = Failure(RepositoryError("db down"))
        return asyncio.run(_tool_memory_create(ctx, PERSONA, content="hello"))
    if tool_name == "memory_read":
        ctx.memory_service.get_memory.return_value = Failure(RepositoryError("missing"))
        return asyncio.run(_tool_memory_read(ctx, PERSONA, memory_key="mem_001"))
    if tool_name == "memory_update":
        ctx.memory_service.update_memory.return_value = Failure(RepositoryError("locked"))
        return asyncio.run(_tool_memory_update(ctx, PERSONA, memory_key="mem_001", content="updated"))
    if tool_name == "memory_delete":
        ctx.memory_service.delete_memory.return_value = Failure(RepositoryError("locked"))
        return asyncio.run(_tool_memory_delete(ctx, PERSONA, memory_key="mem_001"))
    if tool_name == "memory_search":
        ctx.search_engine.search.return_value = Failure(RepositoryError("engine down"))
        return asyncio.run(_tool_memory_search(ctx, PERSONA, query="q"))
    if tool_name == "memory_stats":
        ctx.memory_service.get_stats.return_value = Failure(RepositoryError("no stats"))
        return asyncio.run(_tool_memory_stats(ctx, PERSONA))
    if tool_name == "update_context":
        # update_context has no returned-failure path — exception path must
        # still publish (audited wrapper catches & re-raises)
        ctx.persona_service.update_emotion.side_effect = RuntimeError("persona locked")
        with pytest.raises(RuntimeError):
            asyncio.run(_tool_update_context(ctx, PERSONA, emotion="joy"))
        return None
    if tool_name == "item_add":
        ctx.equipment_service.add_item.return_value = Failure(RepositoryError("full"))
        return asyncio.run(_tool_item_add(ctx, PERSONA, item_name="sword"))
    if tool_name == "item_equip":
        ctx.equipment_service.equip.return_value = Failure(RepositoryError("slot busy"))
        return asyncio.run(_tool_item_equip(ctx, PERSONA, equipment={"top": "dress"}))
    if tool_name == "item_search":
        ctx.equipment_service.search_items.return_value = Failure(RepositoryError("db down"))
        return asyncio.run(_tool_item_search(ctx, PERSONA, query="sword"))
    if tool_name == "goal_manage":
        ctx.memory_service.get_by_tags.return_value = Failure(RepositoryError("db down"))
        return asyncio.run(_tool_goal_manage(ctx, PERSONA, operation="list"))
    if tool_name == "invoke_skill":
        # no skills anywhere → returned failure {"ok": False}
        return asyncio.run(_tool_invoke_skill(ctx, PERSONA, name="missing_skill", task="t"))
    raise AssertionError(f"unknown tool: {tool_name}")


@pytest.mark.parametrize("tool_name", sorted(TOOLS))
class TestToolCalledAudit:
    def test_success_path_publishes_tool_called(self, mock_app_context, tool_name):
        _setup_success_ctx(mock_app_context)
        _success_call(tool_name, mock_app_context)
        events = _tool_called_events(mock_app_context)
        assert any(e["success"] is True for e in events), f"{tool_name} must publish tool.called on its success path"

    def test_failure_path_publishes_tool_called(self, mock_app_context, tool_name):
        _setup_success_ctx(mock_app_context)
        _failure_call(tool_name, mock_app_context)
        events = _tool_called_events(mock_app_context)
        assert any(e["success"] is False for e in events), f"{tool_name} must publish tool.called on its failure path"
