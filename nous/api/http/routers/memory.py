from __future__ import annotations

import contextlib
import json
from typing import TYPE_CHECKING

from starlette.responses import JSONResponse

from nous.api.http.deps import (
    CreateMemoryRequest,
    UpdateMemoryRequest,
    _memory_to_dict,
    _resolve_persona_from_request,
    _safe_get_context,
    _strength_to_dict,
)
from nous.api.http.routers._error_handlers import error_from_result
from nous.infrastructure.logging.structured import get_logger

if TYPE_CHECKING:
    from starlette.requests import Request

logger = get_logger(__name__)


def register_memory_routes(mcp) -> None:
    @mcp.custom_route("/api/blocks/{persona}", methods=["GET"])
    async def list_blocks_http(request: Request) -> JSONResponse:
        persona = _resolve_persona_from_request(request)
        ctx = _safe_get_context(persona)
        if not ctx:
            return JSONResponse({"blocks": []})
        result = ctx.memory_service.list_blocks()
        blocks = result.value if result.is_ok else []
        return JSONResponse({"persona": persona, "blocks": blocks})

    @mcp.custom_route("/api/blocks/{persona}", methods=["POST"])
    async def create_block_http(request: Request) -> JSONResponse:
        persona = _resolve_persona_from_request(request)
        ctx = _safe_get_context(persona)
        if not ctx:
            return JSONResponse({"error": "Persona not found"}, status_code=404)
        body = await request.json()
        block_name = body.get("block_name", "").strip()
        content = body.get("content", "").strip()
        if not block_name or not content:
            return JSONResponse({"error": "block_name and content required"}, status_code=400)
        result = ctx.memory_service.write_block(
            block_name,
            content,
            block_type=body.get("block_type", "custom"),
            max_tokens=body.get("max_tokens") or 500,
            priority=body.get("priority", 0),
        )
        if result.is_ok:
            return JSONResponse({"ok": True, "block_name": block_name})
        return error_from_result(result)

    @mcp.custom_route("/api/blocks/{persona}/{block_name:path}", methods=["DELETE"])
    async def delete_block_http(request: Request) -> JSONResponse:
        persona = _resolve_persona_from_request(request)
        ctx = _safe_get_context(persona)
        if not ctx:
            return JSONResponse({"error": "Persona not found"}, status_code=404)
        block_name = request.path_params.get("block_name", "")
        result = ctx.memory_service.delete_block(block_name)
        if result.is_ok:
            return JSONResponse({"ok": True})
        return error_from_result(result)

    @mcp.custom_route("/api/observations/{persona}", methods=["GET"])
    async def observations(request: Request) -> JSONResponse:
        persona = _resolve_persona_from_request(request)
        try:
            page = int(request.query_params.get("page", "1"))
            if page < 1 or page > 10000:
                return JSONResponse({"error": "page must be between 1 and 10000"}, status_code=400)
        except ValueError:
            return JSONResponse({"error": "page must be an integer"}, status_code=400)
        try:
            per_page = int(request.query_params.get("per_page", "20"))
            if per_page < 1 or per_page > 1000:
                return JSONResponse({"error": "per_page must be between 1 and 1000"}, status_code=400)
        except ValueError:
            return JSONResponse({"error": "per_page must be an integer"}, status_code=400)
        tag = request.query_params.get("tag") or None
        q = request.query_params.get("q") or None
        sort_order = request.query_params.get("sort", "desc")
        mode = request.query_params.get("mode") or None
        if mode == "recent":
            try:
                limit = int(request.query_params.get("per_page", "10"))
                if limit < 1 or limit > 1000:
                    return JSONResponse({"error": "per_page must be between 1 and 1000"}, status_code=400)
            except ValueError:
                return JSONResponse({"error": "per_page must be an integer"}, status_code=400)
            ctx = _safe_get_context(persona)
            if ctx is None:
                return JSONResponse({"error": f"Persona '{persona}' not found"}, status_code=404)
            result = ctx.memory_service.get_recent(limit=limit)
            if not result.is_ok:
                return error_from_result(result)
            return JSONResponse(
                {
                    "persona": persona,
                    "mode": "recent",
                    "memories": [_memory_to_dict(m) for m in result.value],
                }
            )
        ctx = _safe_get_context(persona)
        if ctx is None:
            return JSONResponse({"error": f"Persona '{persona}' not found"}, status_code=404)
        try:
            result = ctx.memory_repo.find_with_pagination(
                page=page,
                per_page=per_page,
                tag=tag,
                query=q,
                sort_order=sort_order,
            )
            if not result.is_ok:
                return error_from_result(result)
            memories, total_count = result.value
            total_pages = (total_count + per_page - 1) // per_page
            return JSONResponse(
                {
                    "persona": persona,
                    "page": page,
                    "per_page": per_page,
                    "total_count": total_count,
                    "total_pages": total_pages,
                    "memories": [_memory_to_dict(m) for m in memories],
                }
            )
        # 最終防衛線
        except Exception as exc:
            logger.exception("Unexpected error: %s", exc)
            return JSONResponse({"error": "Internal server error"}, status_code=500)

    @mcp.custom_route("/api/strengths/{persona}", methods=["GET"])
    async def memory_strengths(request: Request) -> JSONResponse:
        persona = _resolve_persona_from_request(request)
        ctx = _safe_get_context(persona)
        if ctx is None:
            return JSONResponse({"error": f"Persona '{persona}' not found"}, status_code=404)
        try:
            result = ctx.memory_repo.get_all_strengths()
            if not result.is_ok:
                return error_from_result(result)
            strengths = result.value
            buckets = [0] * 10
            for s in strengths:
                idx = min(int(s.strength * 10), 9)
                buckets[idx] += 1
            histogram = [{"range": f"{i / 10:.1f}-{(i + 1) / 10:.1f}", "count": buckets[i]} for i in range(10)]
            return JSONResponse(
                {
                    "persona": persona,
                    "total": len(strengths),
                    "strengths": [_strength_to_dict(s) for s in strengths],
                    "histogram": histogram,
                }
            )
        # 最終防衛線
        except Exception as exc:
            logger.exception("Unexpected error: %s", exc)
            return JSONResponse({"error": "Internal server error"}, status_code=500)

    @mcp.custom_route("/api/memories/{persona}", methods=["GET"])
    async def list_memories(request: Request) -> JSONResponse:
        persona = _resolve_persona_from_request(request)
        try:
            limit = int(request.query_params.get("limit", "50"))
            if limit < 1 or limit > 1000:
                return JSONResponse({"error": "limit must be between 1 and 1000"}, status_code=400)
        except ValueError:
            return JSONResponse({"error": "limit must be an integer"}, status_code=400)
        try:
            offset = int(request.query_params.get("offset", "0"))
            if offset < 0:
                return JSONResponse({"error": "offset must be non-negative"}, status_code=400)
        except ValueError:
            return JSONResponse({"error": "offset must be an integer"}, status_code=400)
        tag = request.query_params.get("tag") or None
        q = request.query_params.get("query") or None
        sort_order = request.query_params.get("sort_order", "desc")
        ctx = _safe_get_context(persona)
        if ctx is None:
            return JSONResponse({"error": f"Persona '{persona}' not found"}, status_code=404)
        try:
            page = offset // limit + 1
            result = ctx.memory_repo.find_with_pagination(
                page=page,
                per_page=limit,
                tag=tag,
                query=q,
                sort_order=sort_order,
            )
            if not result.is_ok:
                return error_from_result(result)
            memories, total_count = result.value
            return JSONResponse(
                {
                    "persona": persona,
                    "memories": [_memory_to_dict(m) for m in memories],
                    "total": total_count,
                    "limit": limit,
                    "offset": offset,
                }
            )
        # 最終防衛線
        except Exception as exc:
            logger.exception("Unexpected error: %s", exc)
            return JSONResponse({"error": "Internal server error"}, status_code=500)

    @mcp.custom_route("/api/memories/{persona}/{key}", methods=["GET"])
    async def get_memory(request: Request) -> JSONResponse:
        persona = _resolve_persona_from_request(request)
        key = request.path_params.get("key", "")
        if not key:
            return JSONResponse({"error": "Memory key is required"}, status_code=400)
        ctx = _safe_get_context(persona)
        if ctx is None:
            return JSONResponse({"error": f"Persona '{persona}' not found"}, status_code=404)
        try:
            result = ctx.memory_service.get_memory(key)
            if not result.is_ok:
                return JSONResponse({"error": str(result.error)}, status_code=404)
            return JSONResponse({"persona": persona, "memory": _memory_to_dict(result.value)})
        # 最終防衛線
        except Exception as exc:
            logger.exception("Unexpected error: %s", exc)
            return JSONResponse({"error": "Internal server error"}, status_code=500)

    @mcp.custom_route("/api/memories/{persona}", methods=["POST"])
    async def create_memory(request: Request) -> JSONResponse:
        persona = _resolve_persona_from_request(request)
        ctx = _safe_get_context(persona)
        if ctx is None:
            return JSONResponse({"error": f"Persona '{persona}' not found"}, status_code=404)
        try:
            raw = await request.json()
        except (json.JSONDecodeError, TypeError):
            return JSONResponse({"error": "Invalid JSON body"}, status_code=400)
        try:
            body = CreateMemoryRequest(**raw)
        except ValueError as exc:
            logger.exception("Validation error: %s", exc)
            return JSONResponse({"error": "Validation error"}, status_code=422)
        try:
            result = await ctx.memory_service.create_memory(
                content=body.content,
                importance=body.importance,
                emotion=body.emotion,
                emotion_intensity=body.emotion_intensity,
                tags=body.tags,
                privacy_level=body.privacy_level,
                source_context=body.source_context,
            )
            if not result.is_ok:
                return error_from_result(result)
            mem = result.value
            if ctx.vector_store is not None:
                with contextlib.suppress(Exception):
                    await ctx.vector_store.upsert(persona, mem.key, mem.content)
            return JSONResponse(
                {"status": "ok", "memory": _memory_to_dict(mem)},
                status_code=201,
            )
        # 最終防衛線
        except Exception as exc:
            logger.exception("Unexpected error: %s", exc)
            return JSONResponse({"error": "Internal server error"}, status_code=500)

    @mcp.custom_route("/api/memories/{persona}/{key}", methods=["PUT"])
    async def update_memory(request: Request) -> JSONResponse:
        persona = _resolve_persona_from_request(request)
        key = request.path_params.get("key", "")
        if not key:
            return JSONResponse({"error": "Memory key is required"}, status_code=400)
        ctx = _safe_get_context(persona)
        if ctx is None:
            return JSONResponse({"error": f"Persona '{persona}' not found"}, status_code=404)
        try:
            raw = await request.json()
        except (json.JSONDecodeError, TypeError):
            return JSONResponse({"error": "Invalid JSON body"}, status_code=400)
        try:
            body = UpdateMemoryRequest(**raw)
        except ValueError as exc:
            logger.exception("Validation error: %s", exc)
            return JSONResponse({"error": "Validation error"}, status_code=422)
        try:
            updates = body.model_dump(exclude_none=True)
            if not updates:
                return JSONResponse({"error": "No valid fields to update"}, status_code=400)
            result = ctx.memory_service.update_memory(key, **updates)
            if not result.is_ok:
                return JSONResponse({"error": str(result.error)}, status_code=404)
            mem = result.value
            if "content" in updates and ctx.vector_store is not None:
                with contextlib.suppress(Exception):
                    await ctx.vector_store.upsert(persona, mem.key, mem.content)
            return JSONResponse({"status": "ok", "memory": _memory_to_dict(mem)})
        # 最終防衛線
        except Exception as exc:
            logger.exception("Unexpected error: %s", exc)
            return JSONResponse({"error": "Internal server error"}, status_code=500)

    @mcp.custom_route("/api/memories/{persona}/{key}", methods=["DELETE"])
    async def delete_memory(request: Request) -> JSONResponse:
        persona = _resolve_persona_from_request(request)
        key = request.path_params.get("key", "")
        if not key:
            return JSONResponse({"error": "Memory key is required"}, status_code=400)
        ctx = _safe_get_context(persona)
        if ctx is None:
            return JSONResponse({"error": f"Persona '{persona}' not found"}, status_code=404)
        try:
            result = ctx.memory_service.delete_memory(key)
            if not result.is_ok:
                return JSONResponse({"error": str(result.error)}, status_code=404)
            if ctx.vector_store is not None:
                with contextlib.suppress(Exception):
                    await ctx.vector_store.delete(persona, key)
            return JSONResponse({"status": "ok", "deleted": key})
        # 最終防衛線
        except Exception as exc:
            logger.exception("Unexpected error: %s", exc)
            return JSONResponse({"error": "Internal server error"}, status_code=500)
