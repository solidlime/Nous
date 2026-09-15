"""Tests for memory time-context handling.

「過去の記憶が直近の記憶のように扱われる」問題の対策:
- memory_search が age/created_at/updated_at を返すこと（LLM が古さを知り得る）
- recency_weight 既定値で新しさが順位に効くこと
- リフレクションが 24h ウィンドウ外の記憶を拾わないこと（フォールバック廃止）
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nous.domain.memory.entities import Memory
from nous.domain.search.engine import SearchQuery, SearchResult
from nous.domain.search.ranker import RRFRanker
from nous.domain.shared.result import Success

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mem(
    key: str = "mem_001",
    content: str = "test content",
    created_days_ago: float = 0.0,
    importance: float = 0.5,
) -> Memory:
    created = datetime.now(UTC) - timedelta(days=created_days_ago)
    return Memory(
        key=key,
        content=content,
        created_at=created,
        updated_at=created,
        importance=importance,
    )


def _sr(key: str, score: float, created_days_ago: float, importance: float = 0.5) -> SearchResult:
    return SearchResult(
        memory=_mem(key, created_days_ago=created_days_ago, importance=importance), score=score, source="keyword"
    )


def _query(**overrides) -> SearchQuery:
    text: str = overrides.pop("text", "q")
    return SearchQuery(
        text=text,
        importance_weight=overrides.get("importance_weight", 0.0),
        recency_weight=overrides.get("recency_weight", 0.2),
        vector_weight=overrides.get("vector_weight", 1.0),
        keyword_weight=overrides.get("keyword_weight", 0.5),
    )


@pytest.fixture
def registered_tools():
    """register_tools をモック FastMCP に通して、ツール関数を名前で捕まえる。"""
    tools: dict[str, object] = {}

    def mock_tool_decorator():
        def decorator(func):
            tools[func.__name__] = func
            return func

        return decorator

    mock_mcp = MagicMock()
    mock_mcp.tool = mock_tool_decorator

    with (
        patch("nous.api.mcp.tools.AppContextRegistry") as mock_registry_cls,
        patch("nous.api.mcp.tools.get_current_persona", return_value="test_persona"),
    ):
        ctx = MagicMock()
        ctx.memory_service = MagicMock()
        ctx.memory_service.create_memory = AsyncMock()
        ctx.memory_service.count_memories.return_value = Success(0)
        ctx.memory_service.log_search.return_value = Success(None)
        ctx.search_engine = AsyncMock()
        ctx.search_engine.set_persona = MagicMock(return_value=None)
        ctx.search_engine._semantic = None
        ctx.persona_service = MagicMock()
        ctx.equipment_service = MagicMock()
        ctx.entity_service = MagicMock()
        ctx.event_bus = AsyncMock()
        ctx.vector_store = None
        ctx.settings = MagicMock()
        ctx.settings.contradiction_threshold = 0.85
        mock_registry_cls.get.return_value = ctx

        from nous.api.mcp.tools import register_tools

        register_tools(mock_mcp)
        yield tools, ctx


# ---------------------------------------------------------------------------
# 1. memory_search が時刻フィールドを返す
# ---------------------------------------------------------------------------


class TestMemorySearchTimeFields:
    @pytest.mark.asyncio
    async def test_search_result_includes_age_and_timestamps(self, registered_tools):
        """1年前の記憶には "y ago" 相当の age と created_at/updated_at が乗る。"""
        tools, ctx = registered_tools
        sr = SearchResult(memory=_mem("mem_old", created_days_ago=365), score=0.8, source="keyword")
        ctx.search_engine.search.return_value = Success([sr])
        memory_search = tools["memory_search"]
        result = await memory_search(query="test")
        data = json.loads(result)
        assert data["ok"] is True
        entry = data["memories"][0]
        assert entry["key"] == "mem_old"
        assert entry["created_at"] is not None
        assert entry["updated_at"] is not None
        assert entry["age"].endswith("y ago"), f"age={entry['age']}"

    @pytest.mark.asyncio
    async def test_recency_weight_default_is_applied(self, registered_tools):
        """MCP スキーマ既定の recency_weight（0.05）が SearchQuery に渡る。"""
        tools, ctx = registered_tools
        sr = SearchResult(memory=_mem("mem_x"), score=0.8, source="keyword")
        ctx.search_engine.search.return_value = Success([sr])
        memory_search = tools["memory_search"]
        await memory_search(query="test")
        passed = ctx.search_engine.search.call_args[0][0]
        assert passed.recency_weight == 0.05


# ---------------------------------------------------------------------------
# 2. RRFRanker + recency: 順序の性質
# ---------------------------------------------------------------------------


class TestRRFRecencyOrdering:
    def test_equal_relevance_newer_wins(self):
        """関連度が同等なら、既定 recency_weight で新しい記憶が上位に来る。"""
        ranker = RRFRanker()
        results = [_sr("old", 0.8, created_days_ago=365), _sr("new", 0.8, created_days_ago=1 / 24)]
        ranked = ranker.rank(results, _query())
        assert [r.memory.key for r in ranked] == ["new", "old"]

    def test_clear_relevance_gap_survives_moderate_age_gap(self):
        """実運用構成（importance 0.3 + recency 既定 0.05）で、関連度が明確に上の記憶は
        中程度の古さ差（30日 vs 1時間）では逆転しない。

        注: 年単位の古さ差では新しさが勝つ設計（1/(1+age_days) のスケール）。
        その場合は古さを潰すのではなく、age フィールドで LLM に伝えるのが本対策。
        """
        ranker = RRFRanker()
        results = [
            _sr("relevant_old", 0.9, created_days_ago=30, importance=0.9),
            _sr("fresh_weak", 0.5, created_days_ago=1 / 24, importance=0.5),
        ]
        ranked = ranker.rank(results, _query(importance_weight=0.3, recency_weight=0.05))
        assert ranked[0].memory.key == "relevant_old"

    def test_heavier_recency_weight_inverts_clear_relevance_gap(self):
        """境界記録: recency_weight=0.2 では 0.9/30日前 vs 0.5/1時間前 が逆転する。

        1/(1+age_days) は30日で ~0.032 に減衰するため、重み 0.2 のボーナス差
        (~0.19) が importance 差 (0.3*0.4=0.12) を上回る。既定値 0.05 は
        この逆転を避けるために選ばれた（上のテストが通る上限側）。
        """
        ranker = RRFRanker()
        results = [
            _sr("relevant_old", 0.9, created_days_ago=30, importance=0.9),
            _sr("fresh_weak", 0.5, created_days_ago=1 / 24, importance=0.5),
        ]
        ranked = ranker.rank(results, _query(importance_weight=0.3, recency_weight=0.2))
        assert ranked[0].memory.key == "fresh_weak"


# ---------------------------------------------------------------------------
# 3. リフレクションの 24h ウィンドウ（フォールバック廃止）
# ---------------------------------------------------------------------------


def _reflection_ctx(memories: list[Memory]):
    ctx = MagicMock()
    ctx.persona = "test_char"
    ctx.memory_service = MagicMock()
    recent_result = MagicMock()
    recent_result.is_ok = True
    recent_result.value = memories
    ctx.memory_service.get_recent.return_value = recent_result
    tags_result = MagicMock()
    tags_result.is_ok = True
    tags_result.value = []
    ctx.memory_service.get_by_tags.return_value = tags_result
    ctx.search_engine = AsyncMock()
    return ctx


def _reflection_config():
    config = MagicMock()
    config.reflection_threshold = 0.1
    config.reflection_min_interval_hours = 0.0
    config.provider = "test_provider"
    config.extract_model = "test_model"
    config.get_effective_api_key.return_value = "sk-test"
    config.get_effective_model.return_value = "test-model"
    config.get_effective_base_url.return_value = None
    return config


class TestReflection24hWindow:
    @pytest.mark.asyncio
    async def test_skips_when_no_memory_within_24h(self):
        """24h 内の記憶ゼロなら、古い記憶にフォールバックせず skip する。"""
        from nous.application.chat.reflection import maybe_run_reflection

        old_memories = [
            _mem("old_1", created_days_ago=30),
            _mem("old_2", created_days_ago=365),
        ]
        ctx = _reflection_ctx(old_memories)

        def _no_provider(*args, **kwargs):
            raise AssertionError("get_provider must not be called when the 24h window is empty")

        with patch("nous.application.chat.reflection.get_provider", side_effect=_no_provider):
            result = await maybe_run_reflection(ctx, _reflection_config(), recent_importance_sum=5.0)

        assert result == []

    @pytest.mark.asyncio
    async def test_prompt_lines_include_relative_time(self):
        """24h 内の記憶があるとき、リフレクション プロンプトの記憶行に相対時刻が付く。"""
        from nous.application.chat.reflection import maybe_run_reflection
        from nous.infrastructure.llm.base import DoneEvent, TextDeltaEvent

        mem = _mem("mem_now", content="A fresh fact.", created_days_ago=1 / 24)
        ctx = _reflection_ctx([mem])

        captured: dict = {}

        async def fake_stream(**kwargs):
            messages = kwargs.get("messages") or []
            captured["prompt"] = messages[0].content if messages else ""
            insight = json.dumps({"insights": ["Time-aware insight."]})
            yield TextDeltaEvent(content=insight)
            yield DoneEvent(full_content=insight)

        fake_provider = AsyncMock()
        fake_provider.stream = fake_stream
        create_result = MagicMock()
        create_result.is_ok = True
        ctx.memory_service.create_memory = AsyncMock(return_value=create_result)

        with patch("nous.application.chat.reflection.get_provider", return_value=fake_provider):
            result = await maybe_run_reflection(ctx, _reflection_config(), recent_importance_sum=5.0)

        assert result == ["Time-aware insight."]
        assert "A fresh fact." in captured["prompt"]
        assert "h ago" in captured["prompt"]


# ---------------------------------------------------------------------------
# 4. ReflectionEngine._build_system_message の時刻表記
# ---------------------------------------------------------------------------


class TestReflectionEngineSystemMessage:
    def test_memory_lines_include_relative_time(self):
        from nous.application.chat.reflection import ReflectionEngine

        engine = ReflectionEngine(schema=[], config=None)
        memories = [_mem("m1", content="Old fact.", created_days_ago=90)]
        message = engine._build_system_message("test_char", memories)
        assert "- Old fact." in message
        assert "mo ago" in message
        assert "括弧内の時刻を考慮" in message
