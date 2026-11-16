"""v4.x HTTP compat switch — ``?compat=legacy`` restores the pre-envelope shape.

The new format (common envelope ``{ok, data, error}``) is the default; only the
exact value ``legacy`` switches, any other value is ignored. Removed in v5
(plan: docs/archive/superpowers/plans/2026-09-19-v4-release.md, 互換戦略).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from starlette.responses import JSONResponse

if TYPE_CHECKING:
    from starlette.requests import Request

logger = logging.getLogger(__name__)

# NOTE: ``_envelope.py``（MCP 面）とここ（HTTP 面）で封筒を二重定義している。
# MCP 側は json 文字列を返し HTTP 側は dict を返すので共有できない——形状を変える時は両方動かす。


def legacy_requested(request: Request, endpoint: str) -> bool:
    """True only for ``compat=legacy``; logs the deprecation warning when it is."""
    if (request.query_params.get("compat") or "").strip().lower() != "legacy":
        return False
    logger.warning("compat=legacy used: %s", endpoint)
    return True


def envelope_ok(data: Any) -> dict[str, Any]:
    """Success envelope (same contract as ``nous/api/mcp/_envelope.py``)."""
    return {"ok": True, "data": data, "error": None}


def envelope_error(code: str, message: str, status_code: int) -> JSONResponse:
    """Failure envelope with a machine-readable code."""
    return JSONResponse(
        {"ok": False, "data": None, "error": {"code": code, "message": message}},
        status_code=status_code,
    )
