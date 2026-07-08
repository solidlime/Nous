from __future__ import annotations

import asyncio
import io
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING

from starlette.responses import JSONResponse, StreamingResponse

from nous.api.http.deps import (
    _resolve_persona_from_request,
    _safe_get_context,
)
from nous.config.settings import Settings
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
        except Exception as exc:
            logger.exception("Unexpected error: %s", exc)
            return JSONResponse({"error": "Internal server error"}, status_code=500)

    @mcp.custom_route("/api/settings", methods=["PUT"])
    async def update_settings(request: Request) -> JSONResponse:
        try:
            body = await request.json()
        except Exception:
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
        except Exception as exc:
            logger.exception("Unexpected error: %s", exc)
            return JSONResponse({"error": "Internal server error"}, status_code=500)

    @mcp.custom_route("/api/admin/rebuild/{persona}", methods=["POST"])
    async def rebuild_vectors(request: Request) -> JSONResponse:
        persona = _resolve_persona_from_request(request)
        ctx = _safe_get_context(persona)
        if ctx is None:
            return JSONResponse({"error": f"Persona '{persona}' not found"}, status_code=404)
        if ctx.vector_store is None:
            return JSONResponse({"error": "Vector store unavailable"}, status_code=503)
        try:
            loop = asyncio.get_running_loop()
            loop.run_in_executor(None, ctx.vector_store.rebuild_collection, persona)
            return JSONResponse(
                {"status": "accepted", "message": f"Rebuild started for '{persona}'"},
                status_code=202,
            )
        except Exception as exc:
            logger.exception("Unexpected error: %s", exc)
            return JSONResponse({"error": "Internal server error"}, status_code=500)

    @mcp.custom_route("/api/import/{persona}", methods=["POST"])
    async def import_data(request: Request) -> JSONResponse:
        persona = _resolve_persona_from_request(request)
        ctx = _safe_get_context(persona)
        if ctx is None:
            return JSONResponse({"error": f"Persona '{persona}' not found"}, status_code=404)
        try:
            form = await request.form()
            upload = form.get("file")
            if upload is None:
                return JSONResponse({"error": "No file uploaded. Use multipart form field 'file'."}, status_code=400)
            file_bytes = await upload.read()
            if not file_bytes:
                return JSONResponse({"error": "Uploaded file is empty"}, status_code=400)

            settings = Settings()
            import_dir = Path(settings.import_dir)
            import_dir.mkdir(parents=True, exist_ok=True)
            zip_path = import_dir / f"_upload_{persona}.zip"
            zip_path.write_bytes(file_bytes)

            try:
                from nous.migration.importers.legacy_importer import LegacyImporter

                importer = LegacyImporter(ctx.connection, persona)
                result = importer.import_from_zip(str(zip_path))
                if not result.is_ok:
                    return JSONResponse({"error": str(result.error)}, status_code=500)
                return JSONResponse(
                    {
                        "status": "ok",
                        "persona": persona,
                        "imported": result.value,
                    }
                )
            finally:
                if zip_path.exists():
                    zip_path.unlink()
        except Exception as exc:
            logger.exception("Unexpected error: %s", exc)
            return JSONResponse({"error": "Internal server error"}, status_code=500)

    def _build_export_zip(persona_dir: Path) -> io.BytesIO:
        buf = io.BytesIO()
        excluded = {".sqlite-wal", ".sqlite-shm"}
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as zf:
            for file_path in persona_dir.rglob("*"):
                if file_path.is_file() and file_path.suffix not in excluded:
                    arcname = str(file_path.relative_to(persona_dir))
                    zf.write(file_path, arcname)
        buf.seek(0)
        return buf

    @mcp.custom_route("/api/export/{persona}", methods=["GET"])
    async def export_data(request: Request) -> StreamingResponse:
        persona = _resolve_persona_from_request(request)
        settings = Settings()
        persona_dir = Path(settings.data_dir) / persona
        if not persona_dir.exists():
            return JSONResponse({"error": f"Persona '{persona}' not found"}, status_code=404)
        try:
            buf = await asyncio.to_thread(_build_export_zip, persona_dir)
            return StreamingResponse(
                buf,
                media_type="application/zip",
                headers={"Content-Disposition": f'attachment; filename="{persona}_export.zip"'},
            )
        except Exception as exc:
            logger.exception("Unexpected error: %s", exc)
            return JSONResponse({"error": "Internal server error"}, status_code=500)
