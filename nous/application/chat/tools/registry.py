"""ToolRegistry: built-in/MCPツールの統一管理。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from nous.application.chat.tools.builtin import execute_tool, filter_extra_tools, truncate_tool_result
from nous.domain.shared.time_utils import get_now
from nous.infrastructure.logging.structured import get_logger

if TYPE_CHECKING:
    from nous.application.use_cases import AppContext
    from nous.domain.chat_config import ChatConfig
    from nous.infrastructure.llm.base import ToolDefinition
    from nous.infrastructure.mcp_client import MCPClientPool

logger = get_logger(__name__)


class ToolRegistry:
    """built-in + MCP ツールを統一管理し、重複を除去して提供する。"""

    def __init__(
        self,
        builtin_tools: list[ToolDefinition],
        mcp_pool: MCPClientPool | None = None,
    ) -> None:
        extra = mcp_pool.list_all_tools() if mcp_pool else []
        filtered_extra = filter_extra_tools(extra)
        # builtin が優先: 同名の MCP ツールは除外
        builtin_names = {t.name for t in builtin_tools}
        self._builtin = list(builtin_tools)
        self._extra = [t for t in filtered_extra if t.name not in builtin_names]
        self._mcp_pool = mcp_pool

    def add_skills_info(self, skills: list[dict]) -> None:
        """invoke_skill ツールの description に有効スキル一覧を動的注入する。"""
        for i, tool in enumerate(self._builtin):
            if tool.name == "invoke_skill":
                base_desc = tool.description
                if skills:
                    skill_lines = [f"- {s.get('name', '?')}: {s.get('description', '')}" for s in skills]
                    skill_list = "\n".join(skill_lines)
                    new_desc = f"{base_desc}\n\n利用可能なスキル:\n{skill_list}"
                else:
                    new_desc = base_desc
                # 新しい ToolDefinition を作成して置き換え
                self._builtin[i] = ToolDefinition(
                    name=tool.name,
                    description=new_desc,
                    input_schema=tool.input_schema,
                )
                break

    def get_all_tools(self) -> list[ToolDefinition]:
        """重複除去済みの全ツールリストを返す。builtin はアルファベット順（キャッシュ最適化） + MCP は末尾。"""
        return sorted(self._builtin, key=lambda t: t.name) + self._extra

    def is_mcp_tool(self, tool_name: str) -> bool:
        """MCPプール経由で呼ぶべきツールか判定する。"""
        return "__" in tool_name

    async def execute(
        self,
        ctx: AppContext,
        config: ChatConfig,
        tool_name: str,
        tool_input: dict,
    ) -> dict:
        """ツール名に応じて built-in / MCP を自動ルーティングして実行する。"""
        try:
            if self.is_mcp_tool(tool_name):
                if self._mcp_pool is None:
                    return {"status": "error", "message": "MCP pool not available"}
                result = await self._mcp_pool.call_tool(tool_name, tool_input)
            else:
                result = await execute_tool(ctx, config, tool_name, tool_input)

            # Publish tool.called event on success
            if hasattr(ctx, "event_bus") and ctx.event_bus is not None:
                await ctx.event_bus.publish(
                    "tool.called",
                    {
                        "tool_name": tool_name,
                        "params_summary": str(tool_input)[:200],
                        "success": True,
                        "timestamp": get_now().isoformat(),
                    },
                )
            return result
        except Exception as e:
            logger.exception("ToolRegistry.execute failed: %s", tool_name)
            # Publish tool.called event on failure
            if hasattr(ctx, "event_bus") and ctx.event_bus is not None:
                await ctx.event_bus.publish(
                    "tool.called",
                    {
                        "tool_name": tool_name,
                        "params_summary": str(tool_input)[:200],
                        "success": False,
                        "error": str(e),
                        "timestamp": get_now().isoformat(),
                    },
                )
            return {"status": "error", "message": str(e)}

    def truncate_result(self, result: dict, max_chars: int) -> dict:
        return truncate_tool_result(result, max_chars)
