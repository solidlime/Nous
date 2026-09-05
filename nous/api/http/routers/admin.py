from __future__ import annotations

import json
from typing import TYPE_CHECKING

from starlette.responses import JSONResponse

from nous.infrastructure.logging.structured import get_logger

if TYPE_CHECKING:
    from starlette.requests import Request

logger = get_logger(__name__)


def register_admin_routes(mcp) -> None:
    @mcp.custom_route("/api/settings", methods=["GET"])
    async def get_settings(request: Request) -> JSONResponse:
        try:
            from nous.config.runtime_config import RuntimeConfigManager

            config = RuntimeConfigManager()
            return JSONResponse(config.get_all())
        # 最終防衛線
        except Exception as exc:
            logger.exception("Unexpected error: %s", exc)
            return JSONResponse({"error": "Internal server error"}, status_code=500)

    @mcp.custom_route("/api/settings", methods=["PUT"])
    async def update_settings(request: Request) -> JSONResponse:
        try:
            body = await request.json()
        except (json.JSONDecodeError, TypeError):
            logger.exception("update_settings: invalid JSON body")
            return JSONResponse({"error": "Invalid JSON body"}, status_code=400)
        category = body.get("category")
        key = body.get("key")
        value = body.get("value")
        if not category or not key:
            return JSONResponse(
                {"error": "Fields 'category' and 'key' are required"},
                status_code=400,
            )
        try:
            from nous.config.runtime_config import RuntimeConfigManager

            config = RuntimeConfigManager()
            result = config.update(category, key, value)
            if result.get("restart_required"):
                return JSONResponse(content=result, status_code=200)
            status_code = 200 if result.get("success") else 400
            return JSONResponse(result, status_code=status_code)
        # 最終防衛線
        except Exception as exc:
            logger.exception("Unexpected error: %s", exc)
            return JSONResponse({"error": "Internal server error"}, status_code=500)

    @mcp.custom_route("/api/settings/status", methods=["GET"])
    async def settings_status(request: Request) -> JSONResponse:
        try:
            from nous.config.runtime_config import RuntimeConfigManager

            config = RuntimeConfigManager()
            return JSONResponse(
                {
                    "reload_status": config.reload_status.get_all(),
                }
            )
        # 最終防衛線
        except Exception as exc:
            logger.exception("Unexpected error: %s", exc)
            return JSONResponse({"error": "Internal server error"}, status_code=500)

    # d6/d7: rebuild・import・export削除（参照は死にsections＋tests＋docsのみ、liveタブ未使用）
