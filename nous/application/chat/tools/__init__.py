"""Chat tools subpackage."""

from nous.application.chat.tools.builtin import execute_tool, filter_extra_tools, truncate_tool_result
from nous.application.chat.tools.definitions import MEMORY_TOOLS
from nous.application.chat.tools.registry import ToolRegistry

# 後方互換エイリアス（既存 service.py が _truncate_tool_result を import している）
_truncate_tool_result = truncate_tool_result

__all__ = [
    "MEMORY_TOOLS",
    "ToolRegistry",
    "execute_tool",
    "filter_extra_tools",
    "truncate_tool_result",
    "_truncate_tool_result",
]
