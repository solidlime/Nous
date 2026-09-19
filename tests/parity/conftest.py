"""Shared fixtures for tests/parity — red-first parity tests.

These tests are xfail(strict=True) records of audit findings (2026-09-19
design audit): each asserts the DESIRED contract, which current HEAD violates.
When an implementation fixes the asymmetry the test XPASSes and — because of
strict=True — fails loudly, signalling that the xfail marker must be removed.

Run:  uv run --with pytest --with pydantic-settings --with mcp --with fastembed \
             pytest tests/parity -q
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from nous.domain.memory.entities import Memory
from nous.domain.search.engine import SearchResult
from nous.domain.shared.result import Success

UTC = UTC


@pytest.fixture(autouse=True)
def _clear_global_state():
    """Isolate module-level state (query cache / background tasks) between tests."""
    from nous.application.chat.pipeline.post import _background_tasks as _post_bg_tasks
    from nous.domain.memory.service import _background_tasks
    from nous.domain.search.engine import _query_cache

    _query_cache.clear()
    _background_tasks.clear()
    _post_bg_tasks.clear()
    yield
    _query_cache.clear()
    _background_tasks.clear()
    _post_bg_tasks.clear()


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
    ctx.persona_service.get_state_snapshot.return_value = ("neutral", 0.0, {}, None)
    ctx.equipment_service = MagicMock()
    ctx.entity_service = MagicMock()
    ctx.event_bus = AsyncMock()
    ctx.vector_store = None
    ctx.settings = MagicMock()
    ctx.settings.contradiction_threshold = 0.85
    return ctx


def make_memory(key: str = "mem_001", content: str = "test content") -> Memory:
    """Fresh Memory entity with stable timestamps."""
    now = datetime.now(UTC)
    return Memory(key=key, content=content, created_at=now, updated_at=now)


def make_search_result(key: str = "mem_001", score: float = 0.8) -> SearchResult:
    """SearchResult wrapping a fresh Memory."""
    return SearchResult(memory=make_memory(key), score=score, source="keyword")
