from __future__ import annotations

import asyncio

from nous.infrastructure.logging.structured import get_logger
from nous.infrastructure.mcp_client.types import MCPServerConfig, MCPTool

logger = get_logger(__name__)


async def list_tools(config: MCPServerConfig) -> list[MCPTool]:
    import httpx2
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    async def _inner() -> list[MCPTool]:
        _http = httpx2.AsyncClient(headers=dict(config.headers))
        try:
            async with (
                streamable_http_client(config.url, http_client=_http) as (read, write),
                ClientSession(read, write) as session,
            ):
                await session.initialize()
                result = await session.list_tools()
                tools = []
                for tool in result.tools:
                    tools.append(
                        MCPTool(
                            name=f"{config.name}__{tool.name}",
                            description=tool.description or "",
                            input_schema=tool.input_schema if tool.input_schema else {},
                            server_name=config.name,
                            original_name=tool.name,
                        )
                    )
                return tools
        finally:
            await _http.aclose()

    try:
        return await asyncio.wait_for(_inner(), timeout=30.0)
    except Exception as e:
        logger.warning("http_client list_tools failed (%s): %s", config.url, e)
        return []


async def call_tool(config: MCPServerConfig, tool_name: str, args: dict) -> dict:
    """tool_name は original_name（プレフィックスなし）"""
    import httpx2
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    async def _inner() -> dict:
        _http = httpx2.AsyncClient(headers=dict(config.headers))
        try:
            async with (
                streamable_http_client(config.url, http_client=_http) as (read, write),
                ClientSession(read, write) as session,
            ):
                await session.initialize()
                result = await session.call_tool(tool_name, args)
                content_parts = []
                for item in result.content:
                    if hasattr(item, "text"):
                        content_parts.append(item.text)
                    else:
                        content_parts.append(str(item))
                return {"result": "\n".join(content_parts), "isError": result.is_error}
        finally:
            await _http.aclose()

    try:
        return await asyncio.wait_for(_inner(), timeout=30.0)
    except Exception as e:
        logger.warning("http_client call_tool failed (%s/%s): %s", config.url, tool_name, e)
        return {"error": str(e)}
