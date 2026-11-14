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

#: 認証なしで書き換えられると事故になる設定カテゴリ（API キー設定済みのときだけ要求）。
#: ``qdrant.*`` は埋め込み先の差し替え＝データの持ち出し/破棄、``server.*`` は
#: バインド先、``mcp_security.*`` は Host/Origin 検証の無効化。
_DANGEROUS_CATEGORIES = frozenset({"server", "mcp_security", "qdrant"})
_DANGEROUS_KEYS = frozenset(
    {
        ("general", "persona_dir"),
        # 任意の HF リポジトリをロードさせられる（重い処理の外部起動）。
        ("embedding", "model"),
        ("reranker", "model"),
    }
)


def _is_dangerous(category: str, key: str) -> bool:
    return category in _DANGEROUS_CATEGORIES or (category, key) in _DANGEROUS_KEYS


def _require_admin(request: Request) -> JSONResponse | None:
    """``general.api_key`` が設定されていれば Bearer 一致を要求する。

    未設定（初回起動・開発）は素通し — そうしないとキーを立てる前に
    何も設定できなくなる。認証ソースはミドルウェアと同じ（ヘッダ優先、
    無ければ ``?token=``）に揃える。
    """
    from nous.api.mcp.middleware import bearer_from_query, verify_bearer
    from nous.config.runtime_config import RuntimeConfigManager

    current, _ = RuntimeConfigManager().get_effective_value("general", "api_key")
    current = current if isinstance(current, str) else ""
    if not current.strip():
        return None
    provided = request.headers.get("authorization")
    if not provided:
        query_params = getattr(request, "query_params", None)
        query_token = bearer_from_query(str(query_params)) if query_params is not None else None
        if query_token:
            provided = f"Bearer {query_token}"
    if verify_bearer(provided, current.strip()):
        return None
    return JSONResponse({"error": "Valid API key required"}, status_code=401)


def _api_key_gate(request: Request, value: Any) -> JSONResponse | None:
    """Enforce the ``general.api_key`` PUT auth rule (oracle Q9).

    Returns a ``JSONResponse`` (401/400) when the request is rejected,
    else None to let the update proceed.
    """
    gate = _require_admin(request)
    if gate is not None:
        return gate
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
        elif _is_dangerous(category, key):
            # 設定済みの API キーを Bearer で出せないなら危険なキーは触らせない。
            gate = _require_admin(request)
            if gate is not None:
                logger.warning("update_settings: unauthenticated attempt on %s.%s", category, key)
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
