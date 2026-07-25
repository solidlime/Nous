from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from starlette.responses import JSONResponse

from nous.config.settings import Settings
from nous.infrastructure.logging.structured import get_logger

if TYPE_CHECKING:
    from starlette.requests import Request

logger = get_logger(__name__)


async def _do_health() -> dict:
    """Return health check dict."""
    from nous import __version__  # noqa: PLC0415  — avoids circular import

    try:
        from qdrant_client import QdrantClient

        settings = Settings()
        client = QdrantClient(url=settings.qdrant.url, api_key=settings.qdrant.api_key)
        client.get_collections()
        qdrant_ok = True
        client.close()
    except Exception:
        logger.warning("Health check: Qdrant unreachable")
        qdrant_ok = False

    return {
        "status": "ok",
        "version": __version__,
        "qdrant": "connected" if qdrant_ok else "unavailable",
    }


async def health(request: Request) -> JSONResponse:  # noqa: ARG001
    """GET /health — health check."""
    return JSONResponse(await _do_health())


async def _do_list_personas() -> list:
    """Return sorted list of persona names (those with memory.sqlite)."""
    settings = Settings()
    data_path = Path(settings.persona_dir)
    if data_path.exists():
        return sorted([d.name for d in data_path.iterdir() if d.is_dir() and (d / "memory.sqlite").exists()])
    return []


async def list_personas(request: Request) -> JSONResponse:
    """GET /api/personas — list personas."""
    return JSONResponse({"personas": await _do_list_personas()})
