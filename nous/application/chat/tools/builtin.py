"""Built-in tool executor and skill invocation."""

from __future__ import annotations

import json
import os
import re
from typing import TYPE_CHECKING, Any

from nous.api.mcp.tools import TOOL_DISPATCH
from nous.application.chat.tools.definitions import _NOUS_TOOL_NAMES
from nous.config.settings import get_settings
from nous.domain.skill import SkillRepository
from nous.infrastructure.logging.structured import get_logger
from nous.infrastructure.sqlite.connection import get_global_skills_db

if TYPE_CHECKING:
    from nous.application.use_cases import AppContext
    from nous.domain.chat_config import ChatConfig
    from nous.infrastructure.llm.base import ToolDefinition

logger = get_logger(__name__)


def filter_extra_tools(extra_tools: list[ToolDefinition]) -> list[ToolDefinition]:
    """MCP extra ツールから memory 系重複ツールを除外する。"""
    return [t for t in extra_tools if t.name.split("__")[-1] not in _NOUS_TOOL_NAMES]


def _image_ref(b64_str: str, mime_type: str = "image/png") -> str:
    """Convert base64 image data to a compact reference string.

    Handles both raw base64 and data URI format (data:image/...;base64,...).
    Returns something like ``[image: 342KB, image/png]``.
    """
    data = b64_str
    ct = mime_type

    # data: URI 形式の場合、MIME と base64 本体を分離
    if data.startswith("data:"):
        m = re.match(r"^data:([^;]+);base64,(.+)$", data)
        if m:
            ct = m.group(1)
            data = m.group(2)

    # base64 長さから元のバイトサイズを概算 (base64 は 4/3 倍)
    size_bytes = len(data) * 3 // 4
    size_kb = round(size_bytes / 1024)
    return f"[image: {size_kb}KB, {ct}]"


def truncate_tool_result(result: dict, max_chars: int) -> dict:
    """Truncate tool result string to avoid context overflow."""
    has_images = "content_base64" in result or "artifacts" in result
    if has_images:
        logger.info(
            "truncate_tool_result: image data detected (content_base64=%s, artifacts=%d, content_type=%s)",
            "yes" if "content_base64" in result else "no",
            len(result.get("artifacts", [])),
            result.get("content_type", "unknown"),
        )
    if not has_images:
        result_str = json.dumps(result, ensure_ascii=False)
        if len(result_str) <= max_chars:
            return result
        remaining = len(result_str) - max_chars
        return {
            "truncated": True,
            "content": result_str[:max_chars] + f"... [truncated: {remaining} chars remaining]",
        }
    text_parts = {k: v for k, v in result.items() if k not in ("content_base64", "artifacts")}
    text_str = json.dumps(text_parts, ensure_ascii=False)
    if len(text_str) > max_chars:
        text_str = text_str[:max_chars] + "... [truncated]"
    output = {"content": text_str}
    if "content_base64" in result:
        ct = result.get("content_type", "image/png")
        output["content_base64"] = _image_ref(result["content_base64"], ct)
        output["content_type"] = ct
    if "artifacts" in result:
        output["artifacts"] = [_image_ref(a) for a in result["artifacts"]]
    return output


# ── Builtin-only handlers (different from MCP counterparts) ──


async def _handle_context_update(ctx: AppContext, config: ChatConfig, tool_input: dict) -> dict:
    update_kwargs: dict = {}
    if "emotion" in tool_input:
        update_kwargs["emotion"] = tool_input["emotion"]
    if "emotion_intensity" in tool_input:
        update_kwargs["emotion_intensity"] = float(tool_input["emotion_intensity"])
    if "mental_state" in tool_input:
        update_kwargs["mental_state"] = tool_input["mental_state"]
    if update_kwargs:
        if "emotion" in update_kwargs:
            ctx.persona_service.update_emotion(
                ctx.persona,
                update_kwargs["emotion"],
                update_kwargs.get("emotion_intensity", 0.5),
                context="manual_update",
            )
        if "mental_state" in update_kwargs:
            ctx.persona_service.update_physical_state(
                ctx.persona,
                mental_state=update_kwargs["mental_state"],
            )
    # context_note: session continuity — persists in persona_info, displayed in get_context
    if "context_note" in tool_input and tool_input["context_note"]:
        ctx.persona_service.update_persona_info(ctx.persona, {"context_note": tool_input["context_note"]})
    return {"status": "ok"}


# ── MCP-shared handlers (delegate to TOOL_DISPATCH) ──


async def _handle_mcp_dispatch(tool_name: str, ctx: AppContext, config: ChatConfig, tool_input: dict) -> dict:
    """Call shared MCP tool implementation via TOOL_DISPATCH."""
    func = TOOL_DISPATCH.get(tool_name)
    if func is None:
        return {"status": "error", "message": f"Unknown tool: {tool_name}"}

    # ── Parameter mapping: builtin → MCP parameter name diff ──
    mapped_input = dict(tool_input)
    if tool_name == "memory_update" and "new_content" in mapped_input:
        mapped_input["content"] = mapped_input.pop("new_content")

    result_raw = await func(ctx, ctx.persona, **mapped_input)
    # Some MCP functions return JSON string, others return dict
    if isinstance(result_raw, str):
        try:
            result = json.loads(result_raw)
        except json.JSONDecodeError:
            return {"status": "ok", "content": result_raw}  # plain text response
    else:
        result = result_raw

    # Translate core dict format to builtin format
    if result.get("ok"):
        # memory_create duplicate case
        if result.get("status") == "duplicate":
            return {
                "status": "duplicate",
                "similar_to": result.get("similar_to", []),
                "message": result.get("message", ""),
            }
        if "key" in result:
            return {"status": "ok", "key": result["key"]}
        if "memories" in result:
            return {"status": "ok", "memories": result["memories"]}
        if "status" in result:
            return {"status": "ok", "updated": result.get("content", "")}
        if "result" in result:
            return {"result": result["result"]}
        if "files" in result:
            return result  # sandbox_files list
        if "content_base64" in result:
            return result  # sandbox_files read (image)
        if "content" in result:
            return result  # sandbox_files read (text)
        if "path" in result:
            return {"status": "ok", "path": result.get("path", "")}
        return {"status": "ok"}
    return {"status": "error", "message": result.get("error", "unknown")}


# ── Image generation ──

_VALID_IMAGE_SIZES: frozenset[str] = frozenset({"1024x1024", "1792x1024", "1024x1792", "512x512", "768x768"})
_VALID_QUALITIES: frozenset[str] = frozenset({"standard", "hd"})
_VALID_PROVIDERS: frozenset[str] = frozenset(
    {"openai", "stability", "comfyui", "gemini", "replicate", "pollinations", "auto"}
)


async def _handle_image_generate(ctx: AppContext, config: ChatConfig, tool_input: dict) -> dict:
    """DALL-E 3またはStable Diffusionで画像を生成する"""
    if not getattr(config, "image_gen_enabled", False):
        return {"status": "error", "message": "Image generation is disabled. Enable it in chat settings."}

    prompt = str(tool_input.get("prompt", "")).strip()
    if not prompt:
        return {"status": "error", "message": "No prompt provided"}

    # ── validate: size ──
    size = str(tool_input.get("size", "1024x1024"))
    if not re.match(r"^\d+x\d+$", size):
        return {
            "status": "error",
            "message": f"Invalid size format: '{size}'. Expected 'WIDTHxHEIGHT' (e.g. '1024x1024').",
        }
    if size not in _VALID_IMAGE_SIZES:
        valid = ", ".join(sorted(_VALID_IMAGE_SIZES))
        return {"status": "error", "message": f"Unsupported size: '{size}'. Supported sizes: {valid}."}

    # ── validate: quality ──
    quality = str(tool_input.get("quality", "standard"))
    if quality not in _VALID_QUALITIES:
        valid = ", ".join(sorted(_VALID_QUALITIES))
        return {"status": "error", "message": f"Unsupported quality: '{quality}'. Supported values: {valid}."}

    # ── validate: n (clamp 1-4) ──
    try:
        n = int(tool_input.get("n", 1))
    except (ValueError, TypeError):
        return {"status": "error", "message": "Invalid value for 'n': must be an integer between 1 and 4."}
    n = max(1, min(4, n))

    # ── validate: provider ──
    provider_arg = str(tool_input.get("provider", "auto"))
    if provider_arg not in _VALID_PROVIDERS:
        valid = ", ".join(sorted(_VALID_PROVIDERS))
        return {"status": "error", "message": f"Unsupported provider: '{provider_arg}'. Supported providers: {valid}."}

    provider_name = getattr(config, "image_gen_provider", "openai") if provider_arg == "auto" else provider_arg

    try:
        # 開始イベントを送信
        if hasattr(ctx, "event_bus") and ctx.event_bus is not None:
            await ctx.event_bus.publish(
                "sse_event",
                {"type": "image_gen_start", "provider": provider_name, "prompt": prompt[:100], "n": n},
            )

        # プロバイダ選択（ファクトリ経由）
        from nous.infrastructure.image_gen.base import ImageGenConfig
        from nous.infrastructure.image_gen.factory import get_image_gen_provider

        # comfyui_url フォールバック: ChatConfig → portrait_gen
        comfyui_url = getattr(config, "image_gen_comfyui_url", "")
        if not comfyui_url:
            from nous.config.runtime_config import RuntimeConfigManager

            rm = RuntimeConfigManager()
            comfyui_url, _ = rm.get_effective_value("portrait_gen", "comfyui_url")

        # Gemini APIキー解決: RuntimeConfig → env → ChatConfig fallback
        gemini_api_key = ""
        if provider_name == "gemini":
            from nous.config.runtime_config import RuntimeConfigManager

            rm = RuntimeConfigManager()
            gemini_api_key, _ = rm.get_effective_value("api_keys", "openrouter_api_key")
            if not gemini_api_key:
                gemini_api_key = os.environ.get("OPENROUTER_API_KEY", "")
            if not gemini_api_key:
                gemini_api_key = getattr(config, "api_key", "")

        gen_cfg = ImageGenConfig(
            provider=provider_name,
            dalle_model=getattr(config, "image_gen_dalle_model", "dall-e-3"),
            stability_url=getattr(config, "image_gen_stability_url", ""),
            comfyui_url=comfyui_url,
            size=size,
            quality=quality,
            gemini_model=getattr(config, "image_gen_gemini_model", "google/gemini-2.5-flash-image"),
            gemini_api_key=gemini_api_key,
            replicate_model=getattr(config, "image_gen_replicate_model", "black-forest-labs/flux-schnell"),
            replicate_api_key=getattr(config, "image_gen_replicate_api_key", ""),
        )
        provider = get_image_gen_provider(gen_cfg)
        if provider is None:
            if provider_name == "stability" and not gen_cfg.stability_url:
                return {"status": "error", "message": "Stable Diffusion URL is not configured"}
            if provider_name == "comfyui" and not gen_cfg.comfyui_url:
                return {"status": "error", "message": "ComfyUI URL is not configured"}
            return {"status": "error", "message": f"Unsupported provider: {provider_name}"}

        generated = await provider.generate(prompt=prompt, size=size, quality=quality, n=n)

        # 結果を構築
        images_data = [
            {
                "base64": img.base64,
                "revised_prompt": img.revised_prompt,
                "size": img.size,
            }
            for img in generated
        ]

        # 結果イベントを送信
        if hasattr(ctx, "event_bus") and ctx.event_bus is not None:
            await ctx.event_bus.publish(
                "sse_event",
                {"type": "image_gen_result", "images": images_data, "provider": provider_name},
            )

        # サマリーを返す（base64が大きくなるため全文はimagesに入れる）
        summary = f"Generated {len(generated)} image(s)"
        if generated and generated[0].revised_prompt != prompt:
            summary += f"\nRevised prompt: {generated[0].revised_prompt}"

        return {
            "status": "success",
            "message": summary,
            "images": images_data,
        }

    except Exception as e:
        return {"status": "error", "message": f"Image generation failed: {str(e)}"}


async def _handle_list_skills(ctx: AppContext, config: ChatConfig, tool_input: dict) -> dict:
    """List all registered skills from the skill store."""
    try:
        db = get_global_skills_db(get_settings().data_root)
        if db is None:
            return {"status": "error", "message": "Skill store not available"}

        repo = SkillRepository(db)
        skills = repo.list_all()

        # Fallback: sync from filesystem if DB is empty
        if not skills:
            synced = repo.load_from_dir(get_settings().skills_dir)
            if synced:
                skills = repo.list_all()

        items = [
            {
                "name": s.name,
                "description": s.description or "",
                "license": s.license,
                "compatibility": s.compatibility,
            }
            for s in skills
        ]
        return {
            "status": "ok",
            "skills": items,
            "count": len(items),
            "note": "L2 詳細（SKILL.md全文）は invoke_skill ツールで取得してください。",
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ── Handler dispatch table (replaces if/elif chain) ──

_BUILTIN_DISPATCH: dict[str, Any] = {
    "list_skills": _handle_list_skills,
    "image_generate": _handle_image_generate,
}

_MCP_SHARED_TOOLS = frozenset(
    {
        "goal_manage",
        "invoke_skill",
        "update_context",
        "memory_create",
        "memory_search",
        "memory_update",
    }
)


async def execute_tool(ctx: AppContext, config: ChatConfig, tool_name: str, tool_input: dict) -> dict:
    """Execute built-in or shared MCP tool via dispatch table.

    Tools with ``__`` in the name are routed to ``MCPClientPool.call_tool()``
    for external MCP server execution.
    """
    # ── MCP routing gate: tools with "__" go directly to MCP pool ──
    if "__" in tool_name:
        try:
            from nous.infrastructure.mcp_client.pool import MCPClientPool

            pool = MCPClientPool(config.mcp_servers)
            result = await pool.call_tool(tool_name, tool_input)
            # Normalise MCP error responses to builtin status format
            if "error" in result:
                return {"status": "error", "message": result["error"]}

            return result
        except Exception as e:
            logger.exception("MCP tool call failed: %s", tool_name)
            return {"status": "error", "message": str(e)}

    try:
        # Builtin-specific handler
        handler = _BUILTIN_DISPATCH.get(tool_name)
        if handler is not None:
            return await handler(ctx, config, tool_input)

        # Shared MCP tool (delegates to TOOL_DISPATCH)
        if tool_name in _MCP_SHARED_TOOLS:
            return await _handle_mcp_dispatch(tool_name, ctx, config, tool_input)

        return {"status": "error", "message": f"Unknown tool: {tool_name}"}

    except Exception as e:
        logger.exception("Tool execution failed: %s", tool_name)
        return {"status": "error", "message": str(e)}


# invoke_skill is now handled via TOOL_DISPATCH → _tool_invoke_skill in tools.py
