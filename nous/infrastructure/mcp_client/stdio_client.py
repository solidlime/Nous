from __future__ import annotations

import asyncio
import sys

from nous.infrastructure.logging.structured import get_logger
from nous.infrastructure.mcp_client.types import MCPServerConfig, MCPTool

logger = get_logger(__name__)


def _resolve_command(config: MCPServerConfig) -> str:
    """Return sys.executable if config.command is empty or the bare 'python' literal."""
    cmd = config.command
    if not cmd or cmd.strip() == "python":
        return sys.executable
    return cmd


async def list_tools(config: MCPServerConfig) -> list[MCPTool]:
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    async def _inner() -> list[MCPTool]:
        params = StdioServerParameters(command=_resolve_command(config), args=config.args)
        async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
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

    try:
        return await asyncio.wait_for(_inner(), timeout=30.0)
    except Exception as e:
        logger.warning("stdio_client list_tools failed (%s): %s", config.command, e)
        return []


async def call_tool(config: MCPServerConfig, tool_name: str, args: dict) -> dict:
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    async def _inner() -> dict:
        params = StdioServerParameters(command=_resolve_command(config), args=config.args)
        async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(tool_name, args)
            content_parts = []
            for item in result.content:
                if hasattr(item, "text"):
                    content_parts.append(item.text)
                else:
                    content_parts.append(str(item))
            return {"result": "\n".join(content_parts), "isError": result.is_error}

    try:
        return await asyncio.wait_for(_inner(), timeout=30.0)
    except Exception as e:
        logger.warning("stdio_client call_tool failed (%s/%s): %s", config.command, tool_name, e)
        return {"error": str(e)}
