"""Built-in tool executor and skill invocation."""

from __future__ import annotations

import base64
import json
import re
from typing import TYPE_CHECKING, Any

from nous.api.mcp._tools_skill import _tool_invoke_skill
from nous.api.mcp.tools import TOOL_DISPATCH
from nous.application.chat.tools.definitions import _NOUS_TOOL_NAMES
from nous.config.settings import get_settings
from nous.domain.skill import SkillRepository
from nous.infrastructure.logging.structured import get_logger

if TYPE_CHECKING:
    from nous.application.use_cases import AppContext
    from nous.domain.chat_config import ChatConfig
    from nous.infrastructure.llm.base import ToolDefinition

logger = get_logger(__name__)

# ── 画像生成モード → ChatConfig 属性名・デフォルト値マッピング ──
_MODE_PREFIX_CONFIG_KEYS: dict[str, str] = {
    "full_body": "image_gen_full_body_prefix",
    "portrait": "image_gen_portrait_prefix",
    "selfie": "image_gen_selfie_prefix",
    "scene": "image_gen_scene_prefix",
}

_MODE_PREFIX_DEFAULTS: dict[str, str] = {
    "full_body": "full body, standing, looking at viewer, ",
    "portrait": "upper body, portrait, looking at viewer, ",
    "selfie": "selfie, from below, mirror selfie, ",
    "scene": "environment shot, full body, ",
}


def _dedup_prompt_tags(combined: str) -> str:
    """Remove duplicate comma-separated tags (case-insensitive, order-preserving)."""
    seen: set[str] = set()
    parts: list[str] = []
    for tag in combined.split(","):
        stripped = tag.strip()
        if not stripped:
            continue
        key = stripped.lower()
        if key not in seen:
            seen.add(key)
            parts.append(stripped)
    return ", ".join(parts)


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
    _IMAGE_KEYS = ("content_base64", "artifacts", "images")
    has_images = any(k in result for k in _IMAGE_KEYS)
    if has_images:
        img_sources = [k for k in _IMAGE_KEYS if k in result]
        imgs_count = len(result.get("images", [])) if "images" in result else None
        logger.info(
            "truncate_tool_result: image data detected from %s (images_count=%s)",
            img_sources,
            imgs_count,
        )
    if not has_images:
        result_str = json.dumps(result, ensure_ascii=False)
        if len(result_str) <= max_chars:
            return dict(result)
        remaining = len(result_str) - max_chars
        return {
            "truncated": True,
            "content": result_str[:max_chars] + f"... [truncated: {remaining} chars remaining]",
        }
    # Build text-only output (exclude all image keys, replace with summary)
    exclude_keys = set(_IMAGE_KEYS)
    text_parts = {k: v for k, v in result.items() if k not in exclude_keys}
    if "images" in result:
        imgs = result["images"]
        n = len(imgs) if isinstance(imgs, list) else "?"
        text_parts["images_summary"] = f"{n} image(s) generated (displayed in chat)"
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


async def _handle_image_generate(ctx: AppContext, config: ChatConfig, tool_input: dict) -> dict:
    """ComfyUIで画像を生成する"""
    if not getattr(config, "image_gen_enabled", False):
        return {"status": "error", "message": "Image generation is disabled. Enable it in chat settings."}

    prompt = str(tool_input.get("prompt", "")).strip()
    if not prompt:
        return {"status": "error", "message": "No prompt provided"}

    # ── validate: preset（プリセット名 → WxH 解決）──
    preset_name = tool_input.get("preset")
    presets: dict[str, str] = getattr(config, "image_gen_presets", {}) or {}
    default_preset: str = getattr(config, "image_gen_default_preset", "square_medium") or "square_medium"

    if preset_name is not None:
        preset_name = str(preset_name)
        if preset_name not in presets:
            available = ", ".join(sorted(presets.keys()))
            return {
                "status": "error",
                "message": f"Unknown preset: '{preset_name}'. Available: {available}.",
            }
        size = presets[preset_name]
    else:
        preset_name = default_preset
        size = presets.get(default_preset, "768x768")

    m = re.match(r"^(\d+)x(\d+)$", size)
    if not m:
        return {"status": "error", "message": f"Invalid preset value: '{size}' for preset '{preset_name}'."}
    w, h = int(m.group(1)), int(m.group(2))

    # 上限クランプ（後方互換: 旧 size 指定のフォールバック）
    max_w = getattr(config, "image_gen_max_width", 1200) or 1200
    max_h = getattr(config, "image_gen_max_height", 1200) or 1200
    w = min(w, max_w)
    h = min(h, max_h)

    # ── validate: n (clamp 1-4) ──
    try:
        n = int(tool_input.get("n", 1))
    except (ValueError, TypeError):
        return {"status": "error", "message": "Invalid value for 'n': must be an integer between 1 and 4."}
    n = max(1, min(4, n))

    provider_name = "comfyui"

    # ── self-portrait mode: auto-inject persona appearance prompt ──
    self_portrait = tool_input.get("self_portrait", False)
    portrait_mode = tool_input.get("mode", "full_body")

    if isinstance(self_portrait, bool) and self_portrait:
        self_prompt = getattr(config, "image_gen_self_portrait_prompt", "")
        if self_prompt:
            config_key = _MODE_PREFIX_CONFIG_KEYS.get(portrait_mode, "")
            mode_prefix = getattr(config, config_key, _MODE_PREFIX_DEFAULTS.get(portrait_mode, ""))
            prompt = _dedup_prompt_tags(f"{self_prompt}, {mode_prefix}, {prompt}")

    try:
        # ── ChatConfig から ComfyUIProvider を直接構築 ──
        from nous.infrastructure.image_gen.base import ImageGenConfig
        from nous.infrastructure.image_gen.comfyui import ComfyUIProvider

        # LoRA リストを JSON からパース
        loras_raw = getattr(config, "image_gen_comfyui_loras", "")
        loras: list[dict] = []
        if loras_raw:
            try:
                loras = json.loads(loras_raw)
                if not isinstance(loras, list):
                    loras = []
            except (json.JSONDecodeError, TypeError):
                pass

        comfyui_url = getattr(config, "image_gen_comfyui_url", "") or "http://localhost:8188"

        gen_cfg = ImageGenConfig(
            provider="comfyui",
            comfyui_url=comfyui_url,
            size=size,
        )
        provider = ComfyUIProvider(
            api_url=gen_cfg.comfyui_url,
            checkpoint=getattr(config, "image_gen_comfyui_checkpoint", "noobaiXLNAIXL_epsilonPred11Version.safetensors"),
            loras=loras,
            speed_lora_path=getattr(config, "image_gen_comfyui_speed_lora_path", ""),
            speed_lora_weight=getattr(config, "image_gen_comfyui_speed_lora_weight", 1.0),
            speed_lora_method=getattr(config, "image_gen_comfyui_speed_lora_method", ""),
            width=w,
            height=h,
            steps=getattr(config, "image_gen_comfyui_steps", 28),
            cfg=getattr(config, "image_gen_comfyui_cfg", 5.5),
            sampler=getattr(config, "image_gen_comfyui_sampler", "euler_ancestral"),
            scheduler=getattr(config, "image_gen_comfyui_scheduler", "normal"),
            seed=getattr(config, "image_gen_comfyui_seed", 0),
            denoise=getattr(config, "image_gen_comfyui_denoise", 0.7),
            workflow_template=getattr(config, "image_gen_comfyui_workflow_template", ""),
        )

        # ── i2i mode: use uploaded reference image ──
        reference_image = None
        if getattr(config, "image_gen_mode", "t2i") == "i2i":
            from pathlib import Path as _Path
            from nous.config.settings import get_settings as _get_settings
            _persona = getattr(ctx, "persona", "default")
            _settings = _get_settings()
            ref_path = _Path(_settings.data_root) / "persona" / _persona / "images" / "reference.png"
            if ref_path.exists():
                reference_image = ref_path.read_bytes()
            else:
                logger.warning("i2i mode enabled but no reference.png found at %s, falling back to t2i", ref_path)

        negative_prompt = getattr(config, "image_gen_negative_prompt", "") or ""
        generated = await provider.generate(prompt=prompt, size=size, n=n, negative_prompt=negative_prompt, reference_image=reference_image)

        # ── 画像をサーバー側に永続化 ──
        from pathlib import Path

        from nous.config.settings import get_settings
        settings = get_settings()
        persona = getattr(ctx, "persona", "default")
        images_dir = Path(settings.data_root) / "persona" / persona / "images"
        images_dir.mkdir(parents=True, exist_ok=True)

        import time as _time
        timestamp = int(_time.time())

        # 結果を構築
        images_data = []
        for idx, img in enumerate(generated):
            # ディスクに保存
            img_bytes = base64.b64decode(img.base64)
            prefix = "self_" if self_portrait else ""
            filename = f"{prefix}{timestamp}_{idx:02d}.png"
            img_path = images_dir / filename
            img_path.write_bytes(img_bytes)
            url = f"/api/chat/{persona}/persona/images/{filename}"
            images_data.append({
                "base64": img.base64,
                "revised_prompt": img.revised_prompt,
                "negative_prompt": getattr(img, "negative_prompt", "") or "",
                "size": img.size,
                "filename": str(img_path),
                "url": url,
            })

        # 結果イベントを送信（event_busは使われていないが後方互換のため残す）
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
            "provider": provider_name,
            "self_portrait": self_portrait,
        }

    except Exception as e:
        return {"status": "error", "message": f"Image generation failed: {str(e)}"}


async def _handle_list_skills(ctx: AppContext, config: ChatConfig, tool_input: dict) -> dict:
    """List all registered skills from the skill store."""
    try:
        repo = SkillRepository()
        skills = repo.load_from_dir(get_settings().skills_dir, persist=False)

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
            "note": "スキル詳細は invoke_skill('<name>') で取得してください。システムプロンプトにはスキル名と説明のみ含まれています。",
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


async def _handle_invoke_skill(ctx: AppContext, config: ChatConfig, tool_input: dict) -> dict:
    """スキルの内容をDBから取得して返す。別LLM呼び出しは行わない。"""
    name = tool_input.get("name", "")
    logger.info("invoke_skill called: '%s'", name)
    task = tool_input.get("task", "")
    if not name:
        return {"status": "error", "message": "name is required"}
    r = await _tool_invoke_skill(ctx, ctx.persona, name=name, task=task)
    if r.get("ok"):
        return {"status": "ok", "result": r.get("result", "(no response)")}
    return {"status": "error", "message": r.get("error", "unknown")}


# ── Handler dispatch table (replaces if/elif chain) ──

_BUILTIN_DISPATCH: dict[str, Any] = {
    "list_skills": _handle_list_skills,
    "image_generate": _handle_image_generate,
    "invoke_skill": _handle_invoke_skill,
}

_MCP_SHARED_TOOLS = frozenset(
    {
        "goal_manage",
        "update_context",
        "memory_create",
        "memory_search",
        "memory_update",
        "item_add",
        "item_equip",
        "item_search",
    }
)


async def execute_tool(ctx: AppContext, config: ChatConfig, tool_name: str, tool_input: dict) -> dict:
    """Execute built-in or shared MCP tool via dispatch table.

    Tools with ``__`` in the name are routed to ``MCPClientPool.call_tool()``
    for external MCP server execution.
    """
    logger.info("tool called: '%s' args=%s", tool_name, json.dumps(tool_input, ensure_ascii=False)[:200])
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


# invoke_skill is now handled via _BUILTIN_DISPATCH → _handle_invoke_skill
