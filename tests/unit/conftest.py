"""Shared fixtures and helpers for unit tests."""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nous.domain.shared.result import Success
from nous.infrastructure.sqlite.connection import SQLiteConnection


@pytest.fixture
def sqlite_conn(tmp_path):
    """Shared SQLiteConnection with fully-initialised schema."""
    conn = SQLiteConnection(data_dir=str(tmp_path), persona="test")
    conn.initialize_schema()
    yield conn
    conn.close()


@pytest.fixture(autouse=True)
def _clear_global_state():
    """Isolate module-level state (query cache / background tasks) between tests."""
    from nous.domain.memory.service import _background_tasks
    from nous.domain.search.engine import _query_cache

    _query_cache.clear()
    _background_tasks.clear()
    yield
    _query_cache.clear()
    _background_tasks.clear()


@pytest.fixture
def mock_app_context():
    """Comprehensive mock app context with all common services."""
    ctx = MagicMock()
    ctx.memory_service = MagicMock()
    ctx.memory_service.create_memory = AsyncMock()
    ctx.memory_service.count_memories.return_value = Success(0)
    ctx.search_engine = AsyncMock()
    ctx.search_engine.set_persona = MagicMock(return_value=None)
    ctx.persona_service = MagicMock()
    ctx.equipment_service = MagicMock()
    ctx.entity_service = MagicMock()
    ctx.event_bus = AsyncMock()
    ctx.vector_store = None
    ctx.settings = MagicMock()
    ctx.settings.contradiction_threshold = 0.85
    return ctx


@asynccontextmanager
async def mcp_tool_context(mock_ctx, persona="test_persona"):
    """Context manager that patches MCP tool dependencies for testing."""
    with (
        patch("nous.api.mcp.tools.AppContextRegistry") as mock_reg,
        patch("nous.api.mcp.tools.get_current_persona", return_value=persona),
    ):
        mock_reg.get.return_value = mock_ctx
        yield mock_reg
