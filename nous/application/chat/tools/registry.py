"""ToolRegistry: built-in/MCPツールの統一管理。"""

from __future__ import annotations

import asyncio
import json
from time import perf_counter
from typing import TYPE_CHECKING

from nous.application.chat.tools.builtin import execute_tool, filter_extra_tools, truncate_tool_result
from nous.application.chat.tools.workspace import artifact_path
from nous.domain.config.redaction import redact_params, redact_text
from nous.domain.shared.time_utils import get_now
from nous.infrastructure.logging.structured import get_logger

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from nous.application.use_cases import AppContext
    from nous.domain.config.chat_config import ChatConfig
    from nous.infrastructure.llm.base import ToolDefinition
    from nous.infrastructure.mcp_client import MCPClientPool

logger = get_logger(__name__)

# search_tools のツール名定数（definitions.py の循環インポート回避のためここで定義）
SEARCH_TOOLS_NAME = "search_tools"

if TYPE_CHECKING:
    # 型エイリアス: search_tools ハンドラ（runtime では使わない）
    SearchHandler = Callable[..., Awaitable[dict]]

# 画像系は truncate_tool_result が参照文字列に潰すので artifact には落とさない
_IMAGE_KEYS = ("content_base64", "artifacts", "images")


def _save_artifact(ctx: AppContext, config: ChatConfig, tool_name: str, result: object) -> str | None:
    """切り詰めが走る場合だけ原文を artifact に落とす。失敗してもツールは成功させる。"""
    max_chars = int(getattr(config, "tool_result_max_chars", 0) or 0)
    if max_chars <= 0 or not isinstance(result, (dict, str)):
        return None
    if isinstance(result, dict) and any(k in result for k in _IMAGE_KEYS):
        return None
    body = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
    if len(body) <= max_chars:
        return None
    try:
        path = artifact_path(getattr(ctx, "persona", "") or "", getattr(ctx, "session_id", None), tool_name)
        path.write_text(body, encoding="utf-8")
    except (OSError, ValueError):
        logger.warning("artifact write failed: %s", tool_name, exc_info=True)
        return None
    return str(path)


class ToolRegistry:
    """built-in + MCP ツールを統一管理し、重複を除去して提供する。"""

    def __init__(
        self,
        builtin_tools: list[ToolDefinition],
        mcp_pool: MCPClientPool | None = None,
        search_handler: SearchHandler | None = None,
    ) -> None:
        extra = mcp_pool.list_all_tools() if mcp_pool else []
        filtered_extra = filter_extra_tools(extra)
        # builtin が優先: 同名の MCP ツールは除外
        builtin_names = {t.name for t in builtin_tools}
        self._builtin = list(builtin_tools)
        self._extra = [t for t in filtered_extra if t.name not in builtin_names]
        self._mcp_pool = mcp_pool
        self._discovered_tools: set[str] = set()
        self._search_handler: SearchHandler | None = search_handler

    def get_all_tools(self) -> list[ToolDefinition]:
        """重複除去済みの全ツールリストを返す。builtin はアルファベット順（キャッシュ最適化） + MCP は末尾。"""
        return sorted(self._builtin, key=lambda t: t.name) + self._extra

    def get_visible_tools(self) -> list[ToolDefinition]:
        """defer_loading=False のツール + セッション中に search_tools で発見済みのツールのみ返す。"""
        all_tools = self.get_all_tools()
        return [
            t
            for t in all_tools
            if not t.defer_loading or t.name in self._discovered_tools or t.name == SEARCH_TOOLS_NAME
        ]

    def mark_discovered(self, tool_name: str) -> None:
        """search_tools で発見されたツールを追跡する。"""
        self._discovered_tools.add(tool_name)

    def set_search_handler(self, handler: SearchHandler) -> None:
        """search_tools 実行ハンドラを後から設定する。"""
        self._search_handler = handler

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
        """ツール名に応じて search_tools / built-in / MCP を自動ルーティングして実行する。"""
        # persona は str の時だけ publish に載せる（未設定/非 str は recorder に
        # "unknown" を委ねる。非 str は SQLite bind 不能で記録が落ちるため）。
        persona = getattr(ctx, "persona", None)
        if not isinstance(persona, str):
            persona = ""
        started = perf_counter()
        timeout_s = float(getattr(config, "tool_timeout_seconds", 120) or 120)
        try:
            # ハングしたツールでターンが終わらなくなるのを防ぐ（TurnHub が解けず 409 固定になる）
            async with asyncio.timeout(timeout_s):
                if tool_name == SEARCH_TOOLS_NAME:
                    if self._search_handler is None:
                        result = {"status": "error", "message": "Tool search handler not available"}
                    else:
                        result = await self._search_handler(ctx, config, tool_input)
                elif self.is_mcp_tool(tool_name):
                    if self._mcp_pool is None:
                        return {"status": "error", "message": "MCP pool not available"}
                    result = await self._mcp_pool.call_tool(tool_name, tool_input)
                else:
                    result = await execute_tool(ctx, config, tool_name, tool_input)

            # 切り詰めで消える原文を残す（builtin / search / MCP 共通）
            artifact = _save_artifact(ctx, config, tool_name, result)
            if artifact and isinstance(result, dict):
                result["artifact_path"] = artifact

            # Publish tool.called event on success.
            # Invariant: MCP tools publish their own events (all paths) —
            # registry only publishes for builtin/search_tools.
            if hasattr(ctx, "event_bus") and ctx.event_bus is not None and not self.is_mcp_tool(tool_name):
                payload = {
                    "tool_name": tool_name,
                    "params_summary": redact_params(tool_input),
                    "success": True,
                    "session_id": getattr(ctx, "session_id", None),
                    "timestamp": get_now().isoformat(),
                    "duration_ms": round((perf_counter() - started) * 1000, 1),
                }
                # workspace ツールは result["audit"] に command/exit_code を載せてくる
                audit = result.get("audit") if isinstance(result, dict) else None
                if isinstance(audit, dict):
                    payload.update(audit)
                if artifact:
                    payload["artifact_path"] = artifact
                if persona:
                    payload["persona"] = persona
                await ctx.event_bus.publish("tool.called", payload)
            return result
        except TimeoutError:
            message = f"ツール実行が{timeout_s:.0f}秒でタイムアウトした"
            logger.warning("ToolRegistry.execute timeout: %s (%.0fs)", tool_name, timeout_s)
            await self._publish_failure(ctx, tool_name, tool_input, message, persona, started)
            return {"status": "error", "message": message}
        except Exception as e:
            logger.exception("ToolRegistry.execute failed: %s", tool_name)
            await self._publish_failure(ctx, tool_name, tool_input, str(e), persona, started)
            return {"status": "error", "message": str(e)}

    async def _publish_failure(
        self,
        ctx: AppContext,
        tool_name: str,
        tool_input: dict,
        error: str,
        persona: str,
        started: float,
    ) -> None:
        """失敗時の tool.called を publish する（MCP は自前で publish するので除外）。"""
        if not hasattr(ctx, "event_bus") or ctx.event_bus is None or self.is_mcp_tool(tool_name):
            return
        payload = {
            "tool_name": tool_name,
            "params_summary": redact_params(tool_input),
            "success": False,
            "error": redact_text(error),
            "session_id": getattr(ctx, "session_id", None),
            "timestamp": get_now().isoformat(),
            "duration_ms": round((perf_counter() - started) * 1000, 1),
        }
        if persona:
            payload["persona"] = persona
        await ctx.event_bus.publish("tool.called", payload)

    def truncate_result(self, result: dict, max_chars: int) -> dict:
        return truncate_tool_result(result, max_chars)
