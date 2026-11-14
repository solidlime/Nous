from __future__ import annotations

import asyncio
import contextlib
import time

from nous.infrastructure.logging.structured import get_logger
from nous.infrastructure.mcp_client.types import MCPServerConfig, MCPTool

logger = get_logger(__name__)

#: ツール一覧の再利用期間。MCP の ``initialize`` + ``list_tools`` は毎ターン
#: 払うには重い（HTTP でもハンドシェイクが 2 往復、stdio ならプロセス spawn）
#: 一方、ツール一覧は滅多に変わらない。変更は遅くとも 60 秒で見える。
_TOOLS_TTL_SECONDS = 60.0

#: ``(name, transport, url, command, args, headers)`` -> (取得時刻, tools)
_tools_cache: dict[tuple, tuple[float, list[MCPTool]]] = {}


def _cache_key(config: MCPServerConfig) -> tuple:
    return (
        config.name,
        config.transport,
        config.url,
        config.command,
        tuple(config.args or ()),
        tuple(sorted((config.headers or {}).items())),
    )


def clear_tools_cache() -> None:
    """テスト・設定変更用。"""
    _tools_cache.clear()


class MCPClientPool:
    """MCPサーバー群を管理するプール。async context managerとして使用。"""

    def __init__(self, server_configs: list[dict]) -> None:
        self._configs: list[MCPServerConfig] = []
        for cfg in server_configs:
            with contextlib.suppress(Exception):
                self._configs.append(MCPServerConfig.model_validate(cfg))
        self._tools: list[MCPTool] = []

    async def __aenter__(self) -> MCPClientPool:
        await self._load_tools()
        return self

    async def _load_tools(self) -> None:
        """TTL 内ならキャッシュ、切れていれば取得する（並行サーバは gather）。"""
        now = time.monotonic()
        pending: list[MCPServerConfig] = []
        for cfg in self._configs:
            if not cfg.enabled:
                continue
            cached = _tools_cache.get(_cache_key(cfg))
            if cached is not None and now - cached[0] < _TOOLS_TTL_SECONDS:
                self._tools.extend(cached[1])
            else:
                pending.append(cfg)
        if not pending:
            return
        results = await asyncio.gather(*(self._fetch_tools(cfg) for cfg in pending), return_exceptions=True)
        for cfg, r in zip(pending, results, strict=True):
            # 空リストはキャッシュしない: 取得失敗も [] で返るので、キャッシュすると
            # 一時的な失敗が「60 秒間ツールゼロ」に固定される。
            if isinstance(r, list) and r:
                self._tools.extend(r)
                _tools_cache[_cache_key(cfg)] = (time.monotonic(), r)

    async def __aexit__(self, *args: object) -> None:
        # 接続は保持していない（呼び出しごとに開いて閉じる）。ツール一覧だけが
        # ``_tools_cache`` に残る。
        pass

    async def _fetch_tools(self, config: MCPServerConfig) -> list[MCPTool]:
        try:
            if config.transport == "http":
                from nous.infrastructure.mcp_client.http_client import list_tools
            else:
                from nous.infrastructure.mcp_client.stdio_client import list_tools
            return await list_tools(config)
        except Exception as e:
            logger.warning("MCPClientPool: failed to fetch tools from %s: %s", config.name, e)
            return []

    def list_all_tools(self) -> list:
        """全サーバーのツールをToolDefinitionリストとして返す。"""
        from nous.infrastructure.llm.base import ToolDefinition

        return [
            ToolDefinition(
                name=tool.name,
                description=f"[{tool.server_name}] {tool.description}",
                input_schema=tool.input_schema,
            )
            for tool in self._tools
        ]

    async def call_tool(self, qualified_name: str, args: dict) -> dict:
        """qualified_name = "{server_name}__{tool_name}" でルーティング。"""
        if "__" not in qualified_name:
            return {"error": f"Invalid qualified tool name: {qualified_name}"}
        server_name, tool_name = qualified_name.split("__", 1)
        config = next((c for c in self._configs if c.name == server_name), None)
        if not config:
            return {"error": f"MCP server not found: {server_name}"}
        try:
            if config.transport == "http":
                from nous.infrastructure.mcp_client.http_client import call_tool
            else:
                from nous.infrastructure.mcp_client.stdio_client import call_tool
            return await call_tool(config, tool_name, args)
        except Exception as e:
            logger.warning("MCPClientPool: call_tool failed %s: %s", qualified_name, e)
            return {"error": str(e)}
