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
from nous.infrastructure.logging.structured import get_logger

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
