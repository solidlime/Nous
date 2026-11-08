"""wiki 手動トリガ API（ドリーミング）— 計画書 §4.2「周期 cycle + 手動トリガ API」.

周期 worker は 24h 間隔なので、初回検証やページ修復を即座に流すための入口。
認証は events/ingest と同型（plugin API key）— 外部から書き込みを起こせる面は
既存の外部トリガ面と同じ鍵で守る。
"""

from __future__ import annotations

import secrets
import threading
from typing import TYPE_CHECKING

from starlette.responses import JSONResponse

from nous.api.http.deps import _safe_get_context
from nous.domain.shared.result import Failure, Success
from nous.infrastructure.logging.structured import get_logger
from nous.infrastructure.wiki.store import WikiStore, WikiStoreError

if TYPE_CHECKING:
    from starlette.requests import Request

logger = get_logger(__name__)


def _plugin_key_gate(request: Request, ctx) -> JSONResponse | None:
    """plugin API key を検査する（events/ingest と同じ規則）。"""
    plugin_cfg = ctx.settings.plugin
    if not plugin_cfg.enabled:
        return JSONResponse({"error": "Plugin API is disabled"}, status_code=403)
    if not plugin_cfg.api_key:
        return JSONResponse({"error": "Plugin API misconfigured: api_key not set"}, status_code=500)
    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        return JSONResponse({"error": "Missing or invalid Authorization header"}, status_code=401)
    token = auth_header.removeprefix("Bearer ").strip()
    if not secrets.compare_digest(token, plugin_cfg.api_key):
        return JSONResponse({"error": "Invalid API key"}, status_code=401)
    return None


def register_wiki_routes(mcp) -> None:
    @mcp.custom_route("/api/wiki/{persona}", methods=["GET"])
    async def wiki_pages(request: Request) -> JSONResponse:
        """wiki ページの一覧（ダッシュボード閲覧用・読み取り専用）。"""
        persona = request.path_params["persona"]
        ctx = _safe_get_context(persona)
        if ctx is None:
            return JSONResponse({"error": "Persona not found"}, status_code=404)
        try:
            pages = WikiStore(ctx.settings.data_root, persona).list_pages()
        except WikiStoreError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        items = [
            {
                "slug": p.slug,
                "title": p.title,
                "project": p.project,
                "sources": list(p.sources),
                "links": list(p.links),
                "updated": p.updated,
            }
            for p in sorted(pages, key=lambda p: p.updated or "", reverse=True)
        ]
        return JSONResponse({"persona": persona, "pages": items})

    @mcp.custom_route("/api/wiki/{persona}/{slug:path}", methods=["GET"])
    async def wiki_page(request: Request) -> JSONResponse:
        """wiki ページ 1 枚の本文（markdown 生）を返す。"""
        persona = request.path_params["persona"]
        slug = request.path_params["slug"]
        ctx = _safe_get_context(persona)
        if ctx is None:
            return JSONResponse({"error": "Persona not found"}, status_code=404)
        try:
            result = WikiStore(ctx.settings.data_root, persona).read_page(slug)
        except WikiStoreError as exc:
            # 不正 slug / traversal 試行もここに落ちる（存在を漏らさない 404）。
            return JSONResponse({"error": str(exc)}, status_code=404)
        if isinstance(result, Failure):
            return JSONResponse({"error": str(result.error)}, status_code=404)
        page = result.value
        return JSONResponse(
            {
                "slug": page.slug,
                "title": page.title,
                "project": page.project,
                "sources": list(page.sources),
                "links": list(page.links),
                "updated": page.updated,
                "manual": page.manual,
                "body": page.body,
            }
        )

    @mcp.custom_route("/api/wiki/{persona}/{slug:path}", methods=["PUT"])
    async def wiki_save(request: Request) -> JSONResponse:
        """ダッシュボードからの手書き保存（manual ページとして固定）。

        既存ページなら sources / project を引き継ぎ、編纂 worker が上書きしない
        ように ``manual: true`` を立てる。新規 slug なら空 sources で作る。
        """
        persona = request.path_params["persona"]
        slug = request.path_params["slug"]
        ctx = _safe_get_context(persona)
        if ctx is None:
            return JSONResponse({"error": "Persona not found"}, status_code=404)
        try:
            raw = await request.json()
        except Exception:
            return JSONResponse({"error": "Invalid JSON body"}, status_code=400)
        if not isinstance(raw, dict):
            return JSONResponse({"error": "Invalid JSON body"}, status_code=400)
        body = raw.get("body")
        if not isinstance(body, str) or not body.strip():
            return JSONResponse({"error": "body is required"}, status_code=400)
        try:
            store = WikiStore(ctx.settings.data_root, persona)
        except WikiStoreError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

        existing = store.read_page(slug)
        prior = existing.value if isinstance(existing, Success) else None
        title = raw.get("title")
        if not isinstance(title, str) or not title.strip():
            title = prior.title if prior else slug
        project = raw.get("project")
        if not isinstance(project, str):
            project = prior.project if prior else None

        written = store.write_page(
            slug,
            title,
            body,
            project=project,
            sources=prior.sources if prior else (),
            manual=True,
        )
        if isinstance(written, Failure):
            return JSONResponse({"error": str(written.error)}, status_code=400)
        page = written.value
        logger.info("wiki page saved from dashboard: persona=%s slug=%s", persona, slug)
        return JSONResponse(
            {
                "slug": page.slug,
                "title": page.title,
                "project": page.project,
                "sources": list(page.sources),
                "links": list(page.links),
                "updated": page.updated,
                "manual": page.manual,
                "body": page.body,
            }
        )

    @mcp.custom_route("/api/wiki/run/{persona}", methods=["POST"])
    async def wiki_run(request: Request) -> JSONResponse:
        """1 cycle を即時実行する（非同期・202 で受付だけ返す）。"""
        persona = request.path_params["persona"]
        ctx = _safe_get_context(persona)
        if ctx is None:
            return JSONResponse({"error": "Persona not found"}, status_code=404)

        rejected = _plugin_key_gate(request, ctx)
        if rejected is not None:
            return rejected
        if not ctx.settings.wiki.enabled:
            return JSONResponse({"error": "wiki worker is disabled (NOUS_WIKI__ENABLED=false)"}, status_code=409)

        def _run() -> None:
            try:
                from nous.application.workers.wiki_worker import WikiWorker

                WikiWorker(ctx.settings)._compile_persona(ctx, persona)
            except Exception:
                logger.exception("wiki manual run failed for persona=%s", persona)

        threading.Thread(target=_run, daemon=True, name=f"wiki-manual-{persona}").start()
        logger.info("wiki manual run accepted for persona=%s", persona)
        return JSONResponse({"accepted": True, "persona": persona}, status_code=202)
