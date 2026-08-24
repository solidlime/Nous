from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.tools.base import Tool
from mcp.shared.exceptions import McpError

if TYPE_CHECKING:
    from starlette.requests import Request

from nous import __version__
from nous.api.http.routes import register_http_routes
from nous.api.mcp.middleware import PersonaMiddleware
from nous.api.mcp.tools import register_tools
from nous.application.use_cases import AppContextRegistry
from nous.config.settings import Settings, get_settings
from nous.infrastructure.logging.structured import get_logger, setup_logging

# Set HF_HOME early, before any module triggers huggingface_hub import
# This must happen before huggingface_hub.constants is evaluated
_data_root = os.environ.get("NOUS_DATA_ROOT", str(Path(__file__).resolve().parent.parent / "data"))
os.environ.setdefault("HF_HOME", str(Path(_data_root) / "cache" / "huggingface"))

# ── Monkey-patch Tool.run() to re-raise McpError (preserves JSON-RPC error codes) ──
# FastMCP's Tool.run() wraps all exceptions in ToolError, but McpError must
# propagate unwrapped so the low-level MCP server can convert it to a proper
# JSON-RPC error response (e.g. -32000 PERSONA_REQUIRED).
_original_tool_run = Tool.run

from mcp.server.fastmcp.exceptions import ToolError  # noqa: E402


async def _patched_tool_run(self, arguments, context=None, convert_result=False):
    try:
        return await _original_tool_run(self, arguments, context, convert_result)
    except ToolError as e:
        cause = e.__cause__ or e.__context__
        if isinstance(cause, McpError):
            raise cause from None
        raise
    except McpError:
        raise


Tool.run = _patched_tool_run


class MemoryFastMCP(FastMCP):
    """FastMCP subclass that injects PersonaMiddleware + CORSMiddleware."""

    def _add_cors_middleware(self, app):
        from starlette.middleware.cors import CORSMiddleware

        settings = get_settings()
        cfg = settings.cors
        app.add_middleware(
            CORSMiddleware,
            allow_origins=cfg.allowed_origins,
            allow_credentials=cfg.allow_credentials,
            allow_methods=cfg.allow_methods,
            allow_headers=cfg.allow_headers,
        )

    def streamable_http_app(self):
        app = super().streamable_http_app()
        app.add_middleware(PersonaMiddleware)
        self._add_cors_middleware(app)
        return app

    def sse_app(self, mount_path=None):
        app = super().sse_app(mount_path)
        app.add_middleware(PersonaMiddleware)
        self._add_cors_middleware(app)
        return app


def _mount_static_files(mcp: MemoryFastMCP) -> None:
    """Mount /static/ route for dashboard CSS/JS assets."""
    import mimetypes

    from starlette.responses import FileResponse, Response

    static_dir = Path(__file__).resolve().parent / "api" / "http" / "static"

    @mcp.custom_route("/static/{filepath:path}", methods=["GET", "HEAD"])
    async def serve_static(request: Request):  # noqa: F821
        filepath = request.path_params.get("filepath", "").lstrip("/")
        safe_path = Path(filepath).as_posix().lstrip("/")

        full_path = (static_dir / safe_path).resolve()
        if not full_path.is_relative_to(static_dir.resolve()):
            return Response("Not Found", status_code=404)
        if not full_path.is_file():
            return Response("Not Found", status_code=404)

        mime_type, _ = mimetypes.guess_type(str(full_path))
        return FileResponse(str(full_path), media_type=mime_type or "application/octet-stream")


def create_app() -> MemoryFastMCP:
    """Create and configure the FastMCP application."""
    settings = Settings()
    setup_logging(settings.log_level)
    logger = get_logger("main")

    logger.info("Starting Nous v%s on %s:%s", __version__, settings.server.host, settings.server.port)

    AppContextRegistry.configure(settings)

    # ディレクトリ構造を確保
    settings.ensure_directories()

    # Seed default skills if directory is empty (Docker volume mount may have hidden bundled skills)
    try:
        _default_skills = Path("/opt/nous/default-skills")
        _skills_path = Path(settings.skills_dir)
        if _default_skills.exists() and _default_skills.is_dir():
            _has_skills = (
                any(
                    (_skills_path / d / "SKILL.md").exists()
                    for d in os.listdir(str(_skills_path))
                    if (_skills_path / d).is_dir()
                )
                if _skills_path.exists()
                else False
            )
            if not _has_skills:
                import shutil

                for item in _default_skills.iterdir():
                    dest = _skills_path / item.name
                    if item.is_dir() and not dest.exists():
                        shutil.copytree(str(item), str(dest))
                    elif item.is_file() and not dest.exists():
                        shutil.copy2(str(item), str(dest))
                logger.info("Seeded default skills from %s", str(_default_skills))
    except Exception:
        logger.debug("Skill seeding skipped", exc_info=True)

    # HF_HOME is already set at module level — no need to set again

    mcp = MemoryFastMCP(
        "Nous",
        host=settings.server.host,
        port=settings.server.port,
        stateless_http=True,
        json_response=True,  # Accept: application/json のみでOK（SSE不要）
    )

    # Auto-import on startup
    if settings.import_dir:
        try:
            from nous.application.auto_import import run_auto_import

            results = run_auto_import(settings)
            if results:
                for persona, counts in results.items():
                    logger.info("Auto-imported persona '%s': %s", persona, counts)
        except Exception:
            logger.exception("Auto-import failed")

    register_tools(mcp)
    register_http_routes(mcp)

    # Mount static files for dashboard CSS/JS
    _mount_static_files(mcp)

    # Health check endpoint (docker-compose healthcheck)
    @mcp.custom_route("/health", methods=["GET", "HEAD"])
    async def health(request: Request):  # type: ignore[no-redef]  # noqa: F811
        import json as _json

        from starlette.responses import Response

        status = {"status": "healthy", "services": {}}

        # Check Qdrant
        try:
            from qdrant_client import QdrantClient

            client = QdrantClient(url=settings.qdrant.url, api_key=settings.qdrant.api_key)
            try:
                client.get_collections()
            finally:
                client.close()
            status["services"]["qdrant"] = "ok"
        except Exception as e:
            status["services"]["qdrant"] = f"error: {e}"
            status["status"] = "degraded"

        return Response(
            _json.dumps(status, ensure_ascii=False),
            media_type="application/json",
            status_code=200 if status["status"] == "healthy" else 503,
        )

    # Start background workers
    from nous.application.workers.consolidation_worker import ConsolidationWorker

    consolidation_worker = ConsolidationWorker(settings)
    consolidation_worker.start()

    # Start MemoRAG context snapshot worker
    from nous.domain.chat_config import ChatConfig

    default_config = ChatConfig()
    if settings.memorag.enabled:
        from nous.application.workers.context_snapshot_worker import ContextSnapshotWorker

        snapshot_worker = ContextSnapshotWorker(settings, config=default_config)
        snapshot_worker.start()

    return mcp


mcp = create_app()


def main() -> None:
    """Run the Nous server."""
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
