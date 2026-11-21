"""v2 分割 API — Overview 初回で全量を引かないためのセクション別エンドポイント。

v1 の /api/dashboard/{persona} は互換のため全セクション一括のまま残す。
v2 は「初回 = overview + recent + images の 3 本」で描画できる粒度に割る。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from starlette.responses import JSONResponse

from nous.api.http.routers.persona.persona_dashboard import (
    _build_blocks,
    _build_equipment,
    _build_generated_images,
    _build_goals,
    _build_items,
    _build_recent,
    _build_state_memories,
    _build_stats_context,
    _latest_self_portrait,
)
from nous.api.http.routers.persona.persona_helpers import _resolve_request
from nous.config.settings import get_settings
from nous.infrastructure.logging.structured import get_logger
from nous.infrastructure.wiki.store import WikiStore

if TYPE_CHECKING:
    from starlette.requests import Request

logger = get_logger(__name__)

_DEFAULT_RECENT = 10
_MAX_RECENT = 50
_RECENT_CONTENT_CHARS = 200
_READING_LIMIT = 5
_TRUE = ("1", "true", "yes")


def _slim_memory(d: dict) -> dict:
    """一覧用に本文を切り、重いフィールドを落とす。"""
    return {
        "key": d.get("key"),
        "content": (d.get("content") or "")[:_RECENT_CONTENT_CHARS],
        "tags": d.get("tags") or [],
        "importance": d.get("importance"),
        "created_at": d.get("created_at"),
    }


def _wiki_summary(persona: str) -> dict:
    """KPI の wiki 枚数・プロジェクト数と TODAY'S READING 用の先頭 5 件。

    数え方はフロント（overview-core.js）が /api/wiki の pages から出していたものと
    同じ: 空文字の project はプロジェクトとして数えない。
    """
    try:
        pages = WikiStore(get_settings().data_root, persona).list_pages()
    except Exception:
        logger.debug("v2 overview: wiki summary skipped", exc_info=True)
        return {"pages": 0, "projects": 0, "reading": []}
    projects = {(p.project or "").strip() for p in pages if (p.project or "").strip()}
    reading = [
        {"slug": p.slug, "title": p.title, "updated": p.updated}
        for p in sorted(pages, key=lambda p: p.updated or "", reverse=True)[:_READING_LIMIT]
    ]
    return {"pages": len(pages), "projects": len(projects), "reading": reading}


def _goals_summary(ctx) -> dict:
    goals = _build_goals(ctx)
    return {
        "total": len(goals),
        "active": sum(1 for g in goals if (g.get("status") or "active") == "active"),
    }


def _overview(persona: str, ctx) -> dict:
    """KPI だけの軽量ペイロード（recent / blocks / items / 画像は載せない）。"""
    stats, context = _build_stats_context(persona, ctx)
    return {
        "persona": persona,
        "stats": stats,
        "context": context,
        "state_memories": _build_state_memories(ctx),
        "wiki": _wiki_summary(persona),
        "goals": _goals_summary(ctx),
    }


def _recent(request: Request, persona: str, ctx) -> dict:
    raw = request.query_params.get("limit") or _DEFAULT_RECENT
    try:
        limit = int(raw)
    except (TypeError, ValueError):
        limit = _DEFAULT_RECENT
    limit = max(1, min(limit, _MAX_RECENT))
    rows = _build_recent(ctx, limit)
    if (request.query_params.get("full") or "").lower() in _TRUE:
        return {"persona": persona, "recent": rows}
    return {"persona": persona, "recent": [_slim_memory(m) for m in rows]}


def _images(persona: str, ctx) -> dict:
    return {
        "persona": persona,
        "latest_self_portrait": _latest_self_portrait(persona),
        "generated_images": _build_generated_images(persona, ctx),
    }


def _handler(build):
    """persona 解決 → セクション構築 → JSON。v1 と同じ 404/500 の扱い。"""

    async def _route(request: Request) -> JSONResponse:
        persona, ctx = _resolve_request(request)
        if not ctx:
            return JSONResponse({"error": f"Persona '{persona}' not found"}, status_code=404)
        try:
            return JSONResponse(build(request, persona, ctx))
        # 最終防衛線
        except Exception as exc:
            logger.exception("v2 %s failed: %s", request.url.path, exc)
            return JSONResponse({"error": "Internal server error"}, status_code=500)

    return _route


overview = _handler(lambda request, persona, ctx: _overview(persona, ctx))
recent = _handler(_recent)
blocks = _handler(lambda request, persona, ctx: {"persona": persona, "blocks": _build_blocks(ctx)})
equipment = _handler(lambda request, persona, ctx: {"persona": persona, "equipment": _build_equipment(ctx)})
items = _handler(lambda request, persona, ctx: {"persona": persona, "items": _build_items(ctx)})
goals = _handler(lambda request, persona, ctx: {"persona": persona, "goals": _build_goals(ctx)})
images = _handler(lambda request, persona, ctx: _images(persona, ctx))


def register_persona_v2_routes(mcp) -> None:
    """分割 API（/api/v2/...）。"""
    mcp.custom_route("/api/v2/overview/{persona}", methods=["GET"])(overview)
    mcp.custom_route("/api/v2/recent/{persona}", methods=["GET"])(recent)
    mcp.custom_route("/api/v2/blocks/{persona}", methods=["GET"])(blocks)
    mcp.custom_route("/api/v2/equipment/{persona}", methods=["GET"])(equipment)
    mcp.custom_route("/api/v2/items/{persona}", methods=["GET"])(items)
    mcp.custom_route("/api/v2/goals/{persona}", methods=["GET"])(goals)
    mcp.custom_route("/api/v2/images/{persona}", methods=["GET"])(images)
