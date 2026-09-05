from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from starlette.responses import JSONResponse

from nous.infrastructure.logging.structured import get_logger

if TYPE_CHECKING:
    from starlette.requests import Request

logger = get_logger(__name__)

#: Minimum length for a non-empty ``general.api_key`` value (oracle Q9).
_API_KEY_MIN_LENGTH = 16


def _api_key_gate(request: Request, value: Any) -> JSONResponse | None:
    """Enforce the ``general.api_key`` PUT auth rule (oracle Q9).

    Returns a ``JSONResponse`` (401/400) when the request is rejected,
    else None to let the update proceed.
    """
    from nous.api.mcp.middleware import verify_bearer
    from nous.config.runtime_config import RuntimeConfigManager

    current, _ = RuntimeConfigManager().get_effective_value("general", "api_key")
    current = current if isinstance(current, str) else ""
    if current.strip():
        authorization = request.headers.get("authorization")
        if not verify_bearer(authorization, current.strip()):
            return JSONResponse({"error": "Valid API key required"}, status_code=401)
    if value and (not isinstance(value, str) or len(value) < _API_KEY_MIN_LENGTH):
        return JSONResponse(
            {"error": f"API key must be at least {_API_KEY_MIN_LENGTH} characters"},
            status_code=400,
        )
    return None


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
        if category == "general" and key == "api_key":
            # Oracle Q9: empty effective key = first-boot bootstrap (no auth);
            # non-empty = old-key Bearer required to change or clear ("").
            # Non-empty values shorter than 16 chars are rejected (400).
            gate = _api_key_gate(request, value)
            if gate is not None:
                return gate
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
