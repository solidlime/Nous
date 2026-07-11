"""Built-in tool executor and skill invocation."""

from __future__ import annotations

import json
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
_VALID_PROVIDERS: frozenset[str] = frozenset({"openai", "stability", "auto"})


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

        # プロバイダ選択
        if provider_name == "openai":
            from nous.infrastructure.image_gen.dalle import DalleProvider

            model = getattr(config, "image_gen_dalle_model", "dall-e-3")
            provider = DalleProvider(model=model)
        elif provider_name == "stability":
            from nous.infrastructure.image_gen.stability import StabilityProvider

            stability_url = getattr(config, "image_gen_stability_url", "")
            if not stability_url:
                return {"status": "error", "message": "Stable Diffusion URL is not configured"}
            provider = StabilityProvider(api_url=stability_url)
        else:
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


# ── PDF reading ──


async def _handle_read_pdf(ctx: AppContext, config: ChatConfig, tool_input: dict) -> dict:
    """PDFファイルを解析してテキスト・テーブル・画像を抽出する"""
    import asyncio
    from pathlib import Path

    path = str(tool_input.get("path", "")).strip()
    if not path:
        return {"status": "error", "message": "PDF path not specified"}

    pages = tool_input.get("pages") or None
    mode = str(tool_input.get("mode", "all")).strip()
    max_chars = int(tool_input.get("max_chars", 0))

    if mode not in ("text", "tables", "images", "all"):
        return {
            "status": "error",
            "message": f"Invalid mode: {mode}. Must be one of: text, tables, images, all",
        }

    # ── Local filesystem path ──
    pdf_path = Path(path)
    if not pdf_path.exists():
        return {"status": "error", "message": f"File not found: {path}"}
    if pdf_path.suffix.lower() != ".pdf":
        return {"status": "error", "message": f"Not a PDF file: {path}"}
    # ファイルサイズチェック (50MB上限)
    if pdf_path.stat().st_size > 50 * 1024 * 1024:
        return {"status": "error", "message": "PDF file too large (max: 50MB)"}

    try:
        result = await asyncio.to_thread(_sync_process_pdf, str(pdf_path), pages=pages, mode=mode, max_chars=max_chars)
        result["filename"] = pdf_path.name
        return result
    except ImportError as e:
        missing = str(e).split("'")[1] if "'" in str(e) else str(e)
        return {
            "status": "error",
            "message": f"Missing PDF library: {missing}. Run: pip install PyMuPDF pdfplumber",
        }
    except Exception as e:
        return {"status": "error", "message": f"PDF parse failed: {e}"}


def _parse_page_range(page_spec: str, num_pages: int) -> list[int]:
    """Parse page range like "1-3" or "1,3,5" into 0-indexed page numbers.
    Returns empty list when no valid pages could be parsed.
    """
    if not page_spec or not page_spec.strip():
        return []
    page_set: set[int] = set()
    for part in page_spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            bounds = part.split("-", 1)
            try:
                start = int(bounds[0].strip())
                end = int(bounds[1].strip())
                start_idx = max(0, start - 1)
                end_idx = min(num_pages, end)
                if start_idx < end_idx:
                    page_set.update(range(start_idx, end_idx))
            except ValueError:
                continue
        else:
            try:
                idx = int(part) - 1
                if 0 <= idx < num_pages:
                    page_set.add(idx)
            except ValueError:
                continue
    return sorted(page_set)


def _sync_process_pdf(
    pdf_source: str | bytes,
    pages: str | None = None,
    mode: str = "all",
    max_chars: int = 0,
) -> dict:
    """同期PDF処理 — asyncio.to_thread で実行するために分離"""
    import base64
    import io

    import fitz  # PyMuPDF

    if isinstance(pdf_source, bytes):
        doc = fitz.open(stream=pdf_source, filetype="pdf")
        pdf_path: str | io.BytesIO = io.BytesIO(pdf_source)
    else:
        doc = fitz.open(pdf_source)
        pdf_path = pdf_source
    num_pages = len(doc)

    # ── Page range filtering ──
    target_pages: list[int] | None = None
    if pages:
        parsed = _parse_page_range(pages, num_pages)
        if parsed:
            target_pages = parsed
    page_iter = range(num_pages) if target_pages is None else target_pages

    # Effective text limit: user's max_chars or internal 100K default
    effective_text_limit = max_chars if max_chars > 0 else 100000

    # ── テキスト抽出 (mode: text / all) ──
    text_source = "empty"
    full_text = ""

    if mode in ("text", "all"):
        text_source = "pymupdf"

        # ステージ1: PyMuPDF
        all_text_parts = []
        total_chars = 0
        for page_idx in page_iter:
            page = doc[page_idx]
            text = page.get_text()
            if total_chars + len(text) > effective_text_limit:
                remaining = effective_text_limit - total_chars
                if remaining > 0:
                    all_text_parts.append(text[:remaining])
                all_text_parts.append("\n\n[Text truncated due to reaching the limit]")
                break
            all_text_parts.append(text)
            total_chars += len(text)

        full_text = "\n".join(all_text_parts)

        # ステージ2: pdfplumber フォールバック
        if len(full_text.strip()) < 50:
            try:
                import pdfplumber

                plumber_parts = []
                plumber_total = 0
                with pdfplumber.open(pdf_path) as pdf:
                    plumber_pages = (
                        [pdf.pages[i] for i in target_pages if i < len(pdf.pages)]
                        if target_pages is not None
                        else pdf.pages
                    )
                    for page in plumber_pages:
                        pt = page.extract_text() or ""
                        if plumber_total + len(pt) > effective_text_limit:
                            remaining = effective_text_limit - plumber_total
                            if remaining > 0:
                                plumber_parts.append(pt[:remaining])
                            plumber_parts.append("\n\n[Text truncated due to reaching the limit]")
                            break
                        plumber_parts.append(pt)
                        plumber_total += len(pt)
                plumber_text = "\n".join(plumber_parts)
                if len(plumber_text.strip()) >= 50:
                    full_text = plumber_text
                    text_source = "pdfplumber"
            except Exception:
                pass

        # ステージ3: OCR フォールバック
        if len(full_text.strip()) < 50:
            try:
                import pytesseract  # noqa: F811
                from PIL import Image

                ocr_parts = []
                ocr_page_iter = target_pages if target_pages is not None else range(min(num_pages, 10))
                for page_num in ocr_page_iter:
                    page = doc[page_num]
                    pix = page.get_pixmap()
                    img_bytes = pix.tobytes("png")
                    img = Image.open(io.BytesIO(img_bytes)).convert("L")
                    ocr_text = pytesseract.image_to_string(img, lang="jpn+eng")
                    if ocr_text.strip():
                        ocr_parts.append(f"--- Page {page_num + 1} ---\n{ocr_text.strip()}")
                if ocr_parts:
                    full_text = "\n\n".join(ocr_parts)
                    text_source = "ocr"
                elif not full_text.strip():
                    text_source = "empty"
            except ImportError:
                if not full_text.strip():
                    text_source = "empty"
            except Exception:
                if not full_text.strip():
                    text_source = "empty"

        if text_source == "pymupdf" and not full_text.strip():
            text_source = "empty"
    else:
        # mode = tables / images: no text extraction
        text_source = "skipped"

    # ── テーブル抽出 (mode: tables / all) ──
    tables = []
    if mode in ("tables", "all"):
        try:
            import pdfplumber  # noqa: F811

            with pdfplumber.open(pdf_path) as pdf:
                plumber_page_iter = (
                    [(idx, pdf.pages[idx]) for idx in target_pages if idx < len(pdf.pages)]
                    if target_pages is not None
                    else list(enumerate(pdf.pages))
                )
                for page_num, page in plumber_page_iter:
                    page_tables = page.extract_tables()
                    for table in page_tables:
                        if table and len(table) > 0:
                            headers = [str(h) if h else "" for h in table[0]]
                            rows = [[str(c) if c else "" for c in row] for row in table[1:]] if len(table) > 1 else []
                            tables.append(
                                {
                                    "page": page_num + 1,
                                    "headers": headers,
                                    "rows": rows[:50],
                                }
                            )
        except Exception:
            pass

    # ── 埋め込み画像抽出 (mode: images / all, 最大5枚、1MB/枚上限) ──
    images = []
    if mode in ("images", "all"):
        for page_num in page_iter:
            if len(images) >= 5:
                break
            page = doc[page_num]
            image_list = page.get_images(full=True)
            for img_info in image_list:
                if len(images) >= 5:
                    break
                xref = img_info[0]
                base_image = doc.extract_image(xref)
                image_bytes = base_image["image"]
                if len(image_bytes) > 1_000_000:
                    continue
                images.append(
                    {
                        "page": page_num + 1,
                        "base64": base64.b64encode(image_bytes).decode("utf-8"),
                        "mime_type": f"image/{base_image['ext']}",
                        "source": "embedded",
                    }
                )

        # ── スキャンPDF補完: ページラスター画像 ──
        if not images and text_source == "ocr":
            first_page = next(iter(page_iter), 0)
            page = doc[first_page]
            pix = page.get_pixmap()
            img_bytes = pix.tobytes("png")
            images.append(
                {
                    "page": first_page + 1,
                    "base64": base64.b64encode(img_bytes).decode("utf-8"),
                    "mime_type": "image/png",
                    "source": "page_raster",
                }
            )

    doc.close()

    # Apply max_chars truncation (overrides internal limit if set)
    if max_chars > 0 and len(full_text) > max_chars:
        full_text = full_text[:max_chars] + "\n\n[Text truncated due to reaching the limit]"

    return {
        "status": "success",
        "pages": num_pages,
        "text": full_text,
        "text_source": text_source,
        "tables": tables,
        "images": images,
    }


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
    "read_pdf": _handle_read_pdf,
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
