"""memory_search の時間処理改善のテスト.

- recency_weight 既定値が単一定数から来て、ツールスキーマとハンドラで一致すること
- 結果エントリに created_at / updated_at / age（created_at 基準）が付くこと
- 順位が幾何学的に関連度で決まり、recency が同等関連度のタイブレークになること
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from nous.api.mcp._tools_memory import (
    MEMORY_SEARCH_RECENCY_WEIGHT_DEFAULT,
    _tool_memory_search,
)
from nous.domain.memory.entities import Memory
from nous.domain.search.engine import SearchQuery, SearchResult
from nous.domain.search.ranker import RRFRanker
from nous.domain.shared.result import Success

ONE_YEAR_SECONDS = 366 * 86400  # > 31536000 → "1y ago"（実時刻に依存しない決定性）


def _mem(
    key: str,
    created_ago_seconds: float,
    updated_ago_seconds: float | None = None,
    importance: float = 0.5,
) -> Memory:
    """created_at / updated_at を now からの差で構築するヘルパー."""
    now = datetime.now(UTC)
    created_at = now - timedelta(seconds=created_ago_seconds)
    updated_at = now - timedelta(seconds=updated_ago_seconds or created_ago_seconds)
    return Memory(
        key=key,
        content=f"memory {key}",
        created_at=created_at,
        updated_at=updated_at,
        importance=importance,
    )


# ---------------------------------------------------------------------------
# Fixture: simple MCP registration capture (同じパターンを test_mcp_memory.py から流用)
# ---------------------------------------------------------------------------


@pytest.fixture
def registered_tools(mock_app_context):
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
        mock_registry_cls.get.return_value = mock_app_context

        from nous.api.mcp.tools import register_tools

        register_tools(mock_mcp)
        yield tools, mock_app_context


async def _run_search(ctx, *args, **kwargs):
    """_tool_memory_search を await し JSON を dict で返す（envelope は展開）."""
    payload = json.loads(await _tool_memory_search(ctx, "test_persona", *args, **kwargs))
    return payload.get("data", payload) if payload.get("ok") else payload


class TestRecencyDefaultSingleSource:
    def test_tool_schema_default_equals_single_constant(self, registered_tools):
        """tools.py スキーマの既定値が単一定数と一致（重複定義禁止の検証）。"""
        tools, _ = registered_tools
        import inspect

        sig = inspect.signature(tools["memory_search"])
        assert sig.parameters["recency_weight"].default == MEMORY_SEARCH_RECENCY_WEIGHT_DEFAULT
        assert sig.parameters["recency_weight"].default == 0.05

    def test_handler_default_equals_single_constant(self):
        """ハンドラ関数の既定値も同じ定数を参照する。"""
        import inspect

        sig = inspect.signature(_tool_memory_search)
        assert sig.parameters["recency_weight"].default == MEMORY_SEARCH_RECENCY_WEIGHT_DEFAULT

    @pytest.mark.asyncio
    async def test_default_recency_flows_into_search_query(self, mock_app_context):
        """引数なし呼び出しで recency_weight=0.2 が SearchQuery に渡る。"""
        ctx = mock_app_context
        ctx.search_engine.search.return_value = Success([])
        ctx.search_engine._semantic = None
        ctx.memory_service.log_search.return_value = Success(None)
        data = await _run_search(ctx, query="test")
        assert isinstance(data, dict)  # empty result → {"memories": [], ...}
        call_args = ctx.search_engine.search.call_args[0][0]
        assert isinstance(call_args, SearchQuery)
        assert call_args.recency_weight == MEMORY_SEARCH_RECENCY_WEIGHT_DEFAULT


class TestSearchResultTimeFields:
    @pytest.mark.asyncio
    async def test_time_fields_present_and_age_anchored_on_created_at(self, mock_app_context):
        """created_at/updated_at/age が付き、age は created_at 基準（updated_at に誘導されない）。"""
        ctx = mock_app_context
        # created_at は1年前、updated_at は1時間前（エンリッチで若返った想定）。
        # age は created_at 基準なので "1y ago" になるはず。
        m = _mem("old_enriched", created_ago_seconds=ONE_YEAR_SECONDS, updated_ago_seconds=3600)
        ctx.search_engine.search.return_value = Success([SearchResult(memory=m, score=0.9, source="keyword")])
        ctx.search_engine._semantic = None
        ctx.memory_service.log_search.return_value = Success(None)
        ctx.memory_service.count_memories.return_value = Success(1)

        data = await _run_search(ctx, query="test")
        entry = data["memories"][0]
        assert entry["created_at"] is not None
        assert entry["updated_at"] is not None
        assert entry["age"] == "1y ago"
        # ISO 8601 としてパース可能
        datetime.fromisoformat(entry["created_at"])
        datetime.fromisoformat(entry["updated_at"])

    @pytest.mark.asyncio
    async def test_age_bucket_scales_with_age(self, mock_app_context):
        """1年前 → "y ago"、約3ヶ月 → "mo ago"、直近 → "just now" 相当。"""
        ctx = mock_app_context
        memories = [
            SearchResult(memory=_mem("y", created_ago_seconds=ONE_YEAR_SECONDS), score=0.8, source="keyword"),
            SearchResult(memory=_mem("mo", created_ago_seconds=100 * 86400), score=0.7, source="keyword"),
            SearchResult(memory=_mem("now", created_ago_seconds=30), score=0.6, source="keyword"),
            SearchResult(memory=_mem("h", created_ago_seconds=5 * 3600), score=0.5, source="keyword"),
        ]
        ctx.search_engine.search.return_value = Success(memories)
        ctx.search_engine._semantic = None
        ctx.memory_service.log_search.return_value = Success(None)
        ctx.memory_service.count_memories.return_value = Success(4)

        data = await _run_search(ctx, query="test")
        by_key = {e["key"]: e for e in data["memories"]}
        assert by_key["y"]["age"] == "1y ago"
        assert by_key["mo"]["age"] == "3mo ago"
        assert by_key["now"]["age"] == "just now"
        assert by_key["h"]["age"] == "5h ago"

    @pytest.mark.asyncio
    async def test_no_created_at_means_null_age(self, mock_app_context):
        """created_at がない疑似エントリでは age が None（クラッシュしない）。"""
        ctx = mock_app_context
        no_dt_mem = MagicMock()
        no_dt_mem.key = "bare"
        no_dt_mem.content = "bare content"
        no_dt_mem.importance = 0.5
        no_dt_mem.tags = []
        no_dt_mem.emotion = "neutral"
        no_dt_mem.created_at = None
        no_dt_mem.updated_at = None
        ctx.search_engine.search.return_value = Success([SearchResult(memory=no_dt_mem, score=0.9, source="keyword")])
        ctx.search_engine._semantic = None
        ctx.memory_service.log_search.return_value = Success(None)

        data = await _run_search(ctx, query="test")
        entry = data["memories"][0]
        assert entry["created_at"] is None
        assert entry["age"] is None


class TestRankingRecencyBehavior:
    """RRF ランカーの recency 挙動（ranker は変更しない前提で挙動を固定）。"""

    def test_clear_relevance_gap_keeps_relevant_first_without_recency(self):
        """recency_weight=0では関連度0.9（1年前）が1位を維持し、recencyが順位を乗っ取らない。"""
        old = _mem("relevant", created_ago_seconds=ONE_YEAR_SECONDS)
        new = _mem("irrelevant", created_ago_seconds=3600)
        results = [
            SearchResult(memory=old, score=0.9, source="semantic"),
            SearchResult(memory=new, score=0.5, source="semantic"),
        ]
        ranked = RRFRanker().rank(results, SearchQuery(text="t", recency_weight=0.0, vector_weight=1.0))
        assert [r.memory.key for r in ranked] == ["relevant", "irrelevant"]

    @pytest.mark.asyncio
    async def test_tool_preserves_engine_order_for_clear_relevance_gap(self, mock_app_context):
        """関連度差が明確ならツールはエンジン順を保ち、0.9（1年前）が1位のまま。"""
        ctx = mock_app_context
        old = _mem("relevant", created_ago_seconds=ONE_YEAR_SECONDS)
        new = _mem("irrelevant", created_ago_seconds=3600)
        ctx.search_engine.search.return_value = Success(
            [
                SearchResult(memory=old, score=0.9, source="semantic"),
                SearchResult(memory=new, score=0.5, source="semantic"),
            ]
        )
        ctx.search_engine._semantic = None
        ctx.memory_service.log_search.return_value = Success(None)

        data = await _run_search(ctx, query="test")
        keys = [e["key"] for e in data["memories"]]
        assert keys[0] == "relevant"
        assert keys[1] == "irrelevant"
        # 既定の recency_weight がエンジンに渡っている（順位はエンジンが決定）
        assert ctx.search_engine.search.call_args[0][0].recency_weight == MEMORY_SEARCH_RECENCY_WEIGHT_DEFAULT

    def test_equal_relevance_with_default_recency_prefers_newer(self):
        """関連度が同等なら既定 recency_weight=0.2 で新しい記憶（1時間前）が上位。"""
        old = _mem("old", created_ago_seconds=ONE_YEAR_SECONDS)
        new = _mem("new", created_ago_seconds=3600)
        results = [
            SearchResult(memory=old, score=0.7, source="keyword"),
            SearchResult(memory=new, score=0.7, source="keyword"),
        ]
        ranked = RRFRanker().rank(
            results,
            SearchQuery(text="t", recency_weight=MEMORY_SEARCH_RECENCY_WEIGHT_DEFAULT, keyword_weight=0.5),
        )
        assert [r.memory.key for r in ranked] == ["new", "old"]

    def test_semantic_relevance_edge_still_favors_new_for_equivalent_scores(self):
        """semantic ソースでも同等スコアなら新しい記憶が上位（0.2 既定）。"""
        old = _mem("old", created_ago_seconds=ONE_YEAR_SECONDS)
        new = _mem("new", created_ago_seconds=3600)
        results = [
            SearchResult(memory=old, score=0.8, source="semantic"),
            SearchResult(memory=new, score=0.8, source="semantic"),
        ]
        ranked = RRFRanker().rank(
            results,
            SearchQuery(text="t", recency_weight=MEMORY_SEARCH_RECENCY_WEIGHT_DEFAULT, vector_weight=1.0),
        )
        assert [r.memory.key for r in ranked] == ["new", "old"]
