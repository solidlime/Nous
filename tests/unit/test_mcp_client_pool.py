"""MCPClientPool: ツール一覧の TTL キャッシュ（毎ターンの再ハンドシェイク抑止）。"""

from __future__ import annotations

import pytest

from nous.infrastructure.mcp_client import pool as pool_mod
from nous.infrastructure.mcp_client.pool import MCPClientPool, clear_tools_cache
from nous.infrastructure.mcp_client.types import MCPTool

pytestmark = pytest.mark.unit

CONFIGS = [{"name": "hub", "url": "http://mcp-hub:26263/mcp"}]


@pytest.fixture(autouse=True)
def _clean_cache():
    clear_tools_cache()
    yield
    clear_tools_cache()


@pytest.fixture()
def fetch_counter(monkeypatch):
    calls: list[str] = []

    async def fake_fetch(self, config):
        calls.append(config.name)
        return [
            MCPTool(
                name=f"{config.name}__tool",
                description="d",
                input_schema={},
                server_name=config.name,
                original_name="tool",
            )
        ]

    monkeypatch.setattr(MCPClientPool, "_fetch_tools", fake_fetch)
    return calls


class TestToolsCache:
    @pytest.mark.asyncio
    async def test_second_pool_reuses_cached_tools(self, fetch_counter):
        async with MCPClientPool(CONFIGS) as first:
            assert [t.name for t in first.list_all_tools()] == ["hub__tool"]
        async with MCPClientPool(CONFIGS) as second:
            tools = second.list_all_tools()
        assert len(tools) == 1
        assert tools[0].name == "hub__tool"
        assert fetch_counter == ["hub"], "2 回目はキャッシュから引く（ハンドシェイクしない）"

    @pytest.mark.asyncio
    async def test_cache_expires_after_ttl(self, fetch_counter, monkeypatch):
        monkeypatch.setattr(pool_mod, "_TOOLS_TTL_SECONDS", 0.0)
        async with MCPClientPool(CONFIGS):
            pass
        async with MCPClientPool(CONFIGS):
            pass
        assert fetch_counter == ["hub", "hub"]

    @pytest.mark.asyncio
    async def test_different_url_bypasses_cache(self, fetch_counter):
        async with MCPClientPool(CONFIGS):
            pass
        moved = [{"name": "hub", "url": "http://mcp-hub-2:26263/mcp"}]
        async with MCPClientPool(moved):
            pass
        assert fetch_counter == ["hub", "hub"]

    @pytest.mark.asyncio
    async def test_disabled_server_never_fetched(self, fetch_counter):
        cfgs = [{"name": "hub", "url": "http://mcp-hub:26263/mcp", "enabled": False}]
        async with MCPClientPool(cfgs) as pool:
            assert pool.list_all_tools() == []
        assert fetch_counter == []
