from __future__ import annotations

import json
import logging
from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP  # noqa: TC002
from mcp.shared.exceptions import McpError
from mcp.types import ErrorData
from pydantic import Field

from nous.api.mcp.middleware import PersonaRequiredError, get_current_persona
from nous.application.use_cases import AppContextRegistry

logger = logging.getLogger(__name__)


# =============================================================================
# Core tool implementations — shared between MCP and builtin
# =============================================================================


# ── Re-export core implementations from sub-modules ──
from nous.api.mcp._tools_goal import _tool_goal_manage  # noqa: E402, F401
from nous.api.mcp._tools_helpers import (  # noqa: E402, F401
    _build_time_comment,
    _format_lightweight_response,
    _format_state_block,
    _format_state_diff,
    _parse_days_from_relative,
)
from nous.api.mcp._tools_irodori import _tool_irodori_tts  # noqa: E402, F401
from nous.api.mcp._tools_item import (  # noqa: E402, F401
    _tool_item,
)
from nous.api.mcp._tools_memory import (  # noqa: E402, F401
    _tool_memory_create,
    _tool_memory_delete,
    _tool_memory_read,
    _tool_memory_search,
    _tool_memory_stats,
    _tool_memory_update,
)
from nous.api.mcp._tools_persona import _tool_get_context, _tool_update_context  # noqa: E402, F401
from nous.api.mcp._tools_portrait import _tool_persona_portrait  # noqa: E402, F401
from nous.api.mcp._tools_sandbox import (  # noqa: E402, F401
    _tool_sandbox_context,
    _tool_sandbox_execute,
    _tool_sandbox_files,
    _tool_sandbox_reset,
)
from nous.api.mcp._tools_skill import _tool_invoke_skill  # noqa: E402, F401

# =============================================================================
# Dispatch table — maps tool name → (core_function, docstring)
# =============================================================================

TOOL_DISPATCH: dict[str, Any] = {
    "get_context": _tool_get_context,
    "memory_create": _tool_memory_create,
    "memory_read": _tool_memory_read,
    "memory_update": _tool_memory_update,
    "memory_delete": _tool_memory_delete,
    "memory_search": _tool_memory_search,
    "memory_stats": _tool_memory_stats,
    "update_context": _tool_update_context,
    "item": _tool_item,
    "sandbox_execute": _tool_sandbox_execute,
    "sandbox_files": _tool_sandbox_files,
    "sandbox_reset": _tool_sandbox_reset,
    "sandbox_context": _tool_sandbox_context,
    "goal_manage": _tool_goal_manage,
    "invoke_skill": _tool_invoke_skill,
    "persona_portrait": _tool_persona_portrait,
    "irodori_tts": _tool_irodori_tts,
}


# MCP registration — thin wrappers around core implementations
# =============================================================================


def _parse_description_overrides() -> dict[str, str]:
    """Parse NOUS_TOOL_DESCRIPTION_OVERRIDE env var.
    Format: tool_name=new_description,tool_name2=desc2
    Comma-separated, name=value pairs."""
    import os

    raw = os.environ.get("NOUS_TOOL_DESCRIPTION_OVERRIDE", "")
    if not raw.strip():
        return {}
    overrides: dict[str, str] = {}
    for part in raw.split(","):
        part = part.strip()
        if "=" in part:
            name, desc = part.split("=", 1)
            overrides[name.strip()] = desc.strip()
    return overrides


def register_tools(mcp: FastMCP) -> None:
    """Register flat-named MCP tools (20+ tools)."""
    _desc_overrides = _parse_description_overrides()

    def _tool(name: str):
        """Return @mcp.tool() decorator with optional description override."""
        desc = _desc_overrides.get(name)
        if desc:
            return mcp.tool(description=desc)
        return mcp.tool()

    # get_context
    @_tool("get_context")
    async def get_context() -> str:
        """Get persona state and memory overview. Call FIRST at session start.
        Lightweight: active commitments + essential story + body/emotion state (~500-800 tokens)."""
        p = _resolve_persona()
        return await _tool_get_context(AppContextRegistry.get(p), p)

    # memory_create
    @_tool("memory_create")
    async def memory_create(
        content: str = "",
        importance: float | None = None,
        tags: list[str] | None = None,
        privacy_level: str = "internal",
        source_context: str | None = None,
        kind: str = "semantic",
        defer_vector: bool = False,
        skip_duplicate_check: bool = False,
    ) -> str:
        """Create a memory. Use to record important user facts, preferences, events.
        importance auto-evaluated via LLM when None and enrichment enabled.
        tags: categorization tags. kind: Memory kind — episodic (specific event),
        semantic (general fact), procedural (pattern), prospective (future plan).
        defer_vector: skip immediate vector indexing.
        skip_duplicate_check: skip semantic duplicate detection.

        **Important**: Call context_update/update_context *before* memory_create
        if your emotional or physical state has changed. The system automatically
        snapshots your current persona state (emotions + body_state) at memory creation time —
        this enables searching memories by the emotional/physical context in which they were created.
        When emotion is omitted, the current persona emotion is automatically attached
        (indicated by auto_emotion: true in response)."""
        p = _resolve_persona()
        return await _tool_memory_create(
            AppContextRegistry.get(p),
            p,
            content=content,
            importance=importance,
            tags=tags,
            privacy_level=privacy_level,
            source_context=source_context,
            kind=kind,
            defer_vector=defer_vector,
            skip_duplicate_check=skip_duplicate_check,
        )

    # memory_read
    @_tool("memory_read")
    async def memory_read(memory_key: str | None = None, limit: int = 10, offset: int = 0) -> str:
        """Read a memory by key, or list most recent if key omitted. Use limit/offset for pagination."""
        p = _resolve_persona()
        return await _tool_memory_read(AppContextRegistry.get(p), p, memory_key=memory_key, limit=limit, offset=offset)

    # memory_update
    @_tool("memory_update")
    async def memory_update(
        memory_key: str = "",
        content: str | None = None,
        importance: float | None = None,
        emotion: str | None = None,
        emotion_intensity: float | None = None,
        tags: list[str] | None = None,
        privacy_level: str | None = None,
    ) -> str:
        """Update a memory. Only provided fields are changed.
        importance must be 0.0-1.0. Invalid emotion silently falls back to neutral."""
        p = _resolve_persona()
        return await _tool_memory_update(
            AppContextRegistry.get(p),
            p,
            memory_key=memory_key,
            content=content,
            importance=importance,
            emotion=emotion,
            emotion_intensity=emotion_intensity,
            tags=tags,
            privacy_level=privacy_level,
        )

    # memory_delete
    @_tool("memory_delete")
    async def memory_delete(memory_key: str | None = None, query: str | None = None) -> str:
        """Delete (tombstone) a memory by key or query. Returns key and content snippet of deleted memory."""
        p = _resolve_persona()
        return await _tool_memory_delete(AppContextRegistry.get(p), p, memory_key=memory_key, query=query)

    # memory_search
    @_tool("memory_search")
    async def memory_search(
        query: str,
        top_k: int = 5,
        tags: list[str] | None = None,
        date_range: str | None = None,
        min_importance: float | None = None,
        emotion: str | None = None,
        importance_weight: Annotated[float, Field(ge=0.0, le=1.0)] = 0.0,
        recency_weight: Annotated[float, Field(ge=0.0, le=1.0)] = 0.0,
        vector_weight: Annotated[float, Field(ge=0.0, le=1.0)] = 1.0,
        keyword_weight: Annotated[float, Field(ge=0.0, le=1.0)] = 0.5,
    ) -> str:
        """Search memories with hybrid retrieval. Use when conversation references past events
        or you need context about the user. date_range: "7d","30d","昨日".
        importance_weight/recency_weight: RRF scoring boosts (0.0-1.0).
        vector_weight/keyword_weight: RRF source weights for semantic/keyword signals."""
        p = _resolve_persona()
        return await _tool_memory_search(
            AppContextRegistry.get(p),
            p,
            query=query,
            top_k=top_k,
            tags=tags,
            date_range=date_range,
            min_importance=min_importance,
            emotion=emotion,
            importance_weight=importance_weight,
            recency_weight=recency_weight,
            vector_weight=vector_weight,
            keyword_weight=keyword_weight,
        )

    # memory_stats
    @_tool("memory_stats")
    async def memory_stats(top_n: int = 20) -> str:
        """Get memory statistics: total count, tag/emotion distributions (top_n entries each)."""
        p = _resolve_persona()
        return await _tool_memory_stats(AppContextRegistry.get(p), p, top_n=top_n)

    # update_context
    @_tool("update_context")
    async def update_context(
        emotion: str | None = None,
        emotion_intensity: float | None = None,
        physical_state: str | None = None,
        mental_state: str | None = None,
        environment: str | None = None,
        relationship_status: str | None = None,
        body_state: dict | None = None,
        speech_style: str | None = None,
        context_note: str | None = None,
        user_info: dict | None = None,
        persona_info: dict | None = None,
        nickname: str | None = None,
        relationship_type: str | None = None,
    ) -> str:
        """Update persona state. context_note: short note on current activity (session continuity).
        body_state: {fatigue, warmth, arousal, heart_rate, pain (0.0-1.0)}.
        user_info: {name, nickname, preferred_address}. persona_info: {nickname, ...}."""
        p = _resolve_persona()
        return await _tool_update_context(
            AppContextRegistry.get(p),
            p,
            emotion=emotion,
            emotion_intensity=emotion_intensity,
            physical_state=physical_state,
            mental_state=mental_state,
            environment=environment,
            relationship_status=relationship_status,
            body_state=body_state,
            speech_style=speech_style,
            context_note=context_note,
            user_info=user_info,
            persona_info=persona_info,
            nickname=nickname,
            relationship_type=relationship_type,
        )

    # item (unified, operation-based)
    @_tool("item")
    async def item(
        operation: str,
        item_name: str = "",
        category: str | None = None,
        description: str | None = None,
        quantity: int = 1,
        tags: list[str] | None = None,
        equipment: dict | None = None,
        auto_add: bool = True,
        slots: list[str] | str | None = None,
        query: str | None = None,
        days: int = 7,
    ) -> str:
        """Unified inventory tool. operation: add/remove/equip/unequip/update/search/history.
        Parameters vary by operation — unused ones are ignored.
        Examples:
          item(operation="add", item_name="白いドレス", category="top")
          item(operation="equip", equipment={"top": "白いドレス"})
          item(operation="search", query="ドレス")
          item(operation="history", days=7)"""
        p = _resolve_persona()
        return await _tool_item(
            AppContextRegistry.get(p),
            p,
            operation=operation,
            item_name=item_name,
            category=category,
            description=description,
            quantity=quantity,
            tags=tags,
            equipment=equipment,
            auto_add=auto_add,
            slots=slots,
            query=query,
            days=days,
        )

    # sandbox_execute
    @_tool("sandbox_execute")
    async def sandbox_execute(
        code: str, language: str = "python", libraries: list[str] | None = None, session_id: str | None = None
    ) -> str:
        """Execute code in Docker sandbox. State persists per session.
        language: "python", "js", "bash", "go", "rust".
        libraries: pip packages to install before execution.
        Pass session_id to scope sandbox per conversation session.
        Returns stdout, stderr, exit_code, artifacts (base64 images)."""
        p = _resolve_persona()
        return await _tool_sandbox_execute(
            AppContextRegistry.get(p),
            p,
            code=code,
            language=language,
            libraries=libraries,
            session_id=session_id,
        )

    # sandbox_files
    @_tool("sandbox_files")
    async def sandbox_files(operation: str, path: str = "", content: str | None = None) -> str:
        """Sandbox file operations. operation: list/read/write/append/delete.
        Files are stored in the persona's home directory (bind-mounted per-persona).
        Use /home/sbox_{persona}/ paths — direct persona home paths.
        read auto-detects images (PNG/JPEG/GIF/WebP) returning base64 with PIL resize support."""
        p = _resolve_persona()
        r = await _tool_sandbox_files(AppContextRegistry.get(p), p, operation=operation, path=path, content=content)
        return json.dumps(r, ensure_ascii=False)

    # sandbox_reset
    @_tool("sandbox_reset")
    async def sandbox_reset(level: str = "files") -> str:
        """Reset sandbox environment. level: files (default), packages, full."""
        p = _resolve_persona()
        return await _tool_sandbox_reset(AppContextRegistry.get(p), p, level=level)

    # sandbox_context
    @_tool("sandbox_context")
    async def sandbox_context() -> str:
        """Get sandbox environment context (languages, installed packages)."""
        p = _resolve_persona()
        r = await _tool_sandbox_context(AppContextRegistry.get(p), p)
        return json.dumps(r, ensure_ascii=False)

    # goal_manage
    @_tool("goal_manage")
    async def goal_manage(
        operation: str,
        content: str = "",
        importance: float = 0.75,
        scope: str = "self",
        memory_key: str | None = None,
    ) -> str:
        """Manage goals and interpersonal commitments.
        operation: create/list/achieve/cancel. scope: self (personal goals) / interpersonal (commitments).
        Goals stored as memories with tags=["goal","active/achieved/cancelled"].
        For achieve/cancel, use memory_key to specify the goal directly (content can be empty)."""
        p = _resolve_persona()
        r = await _tool_goal_manage(
            AppContextRegistry.get(p),
            p,
            operation=operation,
            content=content,
            importance=importance,
            scope=scope,
            memory_key=memory_key,
        )
        if r.get("ok"):
            if "key" in r:
                return f"Goal created: {r['key']}"
            if "status" in r:
                return f"Goal {r['status']}: {r['content']}"
            if "result" in r:
                return r["result"]
            return "Goal done"
        return f"Error: {r.get('error', 'unknown')}"

    # invoke_skill
    @_tool("invoke_skill")
    async def invoke_skill(name: str, task: str) -> str:
        """Execute a skill in isolated LLM context. Loads skill from store,
        runs with chat config provider/model. Returns skill output text."""
        p = _resolve_persona()
        r = await _tool_invoke_skill(AppContextRegistry.get(p), p, name=name, task=task)
        if r.get("ok"):
            return r.get("result", "(no response)")
        return f"Error: {r.get('error', 'unknown')}"

    # persona_portrait
    @_tool("persona_portrait")
    async def persona_portrait() -> str:
        """Generate a portrait image for the current persona.
        Uses the configured image provider (ComfyUI / DALL-E / Stability).
        Returns base64-encoded image + prompt metadata,
        or fallback emoji when the provider is unavailable."""
        p = _resolve_persona()
        return await _tool_persona_portrait(AppContextRegistry.get(p), p)

    # irodori_tts
    @_tool("irodori_tts")
    async def irodori_tts(text: str, voice: str | None = None) -> str:
        """Generate TTS audio using Irodori. text: Japanese text to speak. voice: speaker name override."""
        p = _resolve_persona()
        return await _tool_irodori_tts(AppContextRegistry.get(p), p, text=text, voice=voice)

    # ── Chat builtin tool wrappers (delegate to builtin.py handlers) ──

    # browser
    @_tool("browser")
    async def browser(
        action: str,
        url: str = "",
        ref: str = "",
        value: str = "",
        key: str = "",
        what: str = "",
        selector: str = "",
        until: str = "",
        direction: str = "",
        amount: int = 300,
        interactive: bool = True,
    ) -> str:
        """汎用ブラウザ操作。action: open/snapshot/click/fill/get/wait/scroll/press/close。"""
        from nous.application.chat.tools.builtin import _handle_browser
        from nous.domain.chat_config import ChatConfigRepository

        p = _resolve_persona()
        ctx = AppContextRegistry.get(p)
        config = ChatConfigRepository(ctx.connection.get_memory_db()).get(p)
        result = await _handle_browser(
            ctx,
            config,
            {
                "action": action,
                "url": url,
                "ref": ref,
                "value": value,
                "key": key,
                "what": what,
                "selector": selector,
                "until": until,
                "direction": direction,
                "amount": amount,
                "interactive": interactive,
            },
        )
        return json.dumps(result, ensure_ascii=False)

    # search
    @_tool("search")
    async def search(
        query: str,
        num_results: int = 10,
        language: str = "",
    ) -> str:
        """Web検索。query必須。SearXNG経由で結果を返す。"""
        from nous.application.chat.tools.builtin import _handle_search
        from nous.domain.chat_config import ChatConfigRepository

        p = _resolve_persona()
        ctx = AppContextRegistry.get(p)
        config = ChatConfigRepository(ctx.connection.get_memory_db()).get(p)
        result = await _handle_search(
            ctx,
            config,
            {
                "query": query,
                "num_results": num_results,
                "language": language,
            },
        )
        return json.dumps(result, ensure_ascii=False)

    # image_generate
    @_tool("image_generate")
    async def image_generate(
        prompt: str,
        size: str = "1024x1024",
        quality: str = "standard",
        n: int = 1,
        provider: str = "auto",
    ) -> str:
        """画像生成。prompt必須。nは1-4枚、size指定可。"""
        from nous.application.chat.tools.builtin import _handle_image_generate
        from nous.domain.chat_config import ChatConfigRepository

        p = _resolve_persona()
        ctx = AppContextRegistry.get(p)
        config = ChatConfigRepository(ctx.connection.get_memory_db()).get(p)
        result = await _handle_image_generate(
            ctx,
            config,
            {
                "prompt": prompt,
                "size": size,
                "quality": quality,
                "n": n,
                "provider": provider,
            },
        )
        return json.dumps(result, ensure_ascii=False)

    # read_pdf
    @_tool("read_pdf")
    async def read_pdf(path: str) -> str:
        """PDF解析。path必須。テキスト・テーブル・画像抽出。"""
        from nous.application.chat.tools.builtin import _handle_read_pdf
        from nous.domain.chat_config import ChatConfig

        p = _resolve_persona()
        ctx = AppContextRegistry.get(p)
        result = await _handle_read_pdf(ctx, ChatConfig(), {"path": path})
        return json.dumps(result, ensure_ascii=False)

    # list_skills
    @_tool("list_skills")
    async def list_skills() -> str:
        """登録スキル一覧を取得。"""
        from nous.application.chat.tools.builtin import _handle_list_skills
        from nous.domain.chat_config import ChatConfig

        p = _resolve_persona()
        ctx = AppContextRegistry.get(p)
        result = await _handle_list_skills(ctx, ChatConfig(), {})
        return json.dumps(result, ensure_ascii=False)


def _resolve_persona() -> str:
    try:
        return get_current_persona()
    except PersonaRequiredError:
        raise McpError(ErrorData(code=-32000, message="PERSONA_REQUIRED")) from None
