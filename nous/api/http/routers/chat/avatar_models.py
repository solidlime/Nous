"""VRM avatar model API — list / serve / upload VRM models per persona.

Storage: {data_root}/persona/{persona}/avatar/*.vrm
Fallback: repo-internal prototype sample model (never served from static/).
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import TYPE_CHECKING

from starlette.responses import JSONResponse, Response

from nous.api.http.deps import _PERSONA_PATTERN
from nous.api.http.routers.chat.chat_stream import _resolve_request
from nous.config.settings import get_settings
from nous.infrastructure.logging.structured import get_logger

if TYPE_CHECKING:
    from starlette.requests import Request

logger = get_logger(__name__)

_MAX_VRM_BYTES = 100 * 1024 * 1024  # 100MB
_SAFE_FILENAME = re.compile(r"[^A-Za-z0-9._-]")


def _avatar_dir(persona: str) -> Path:
    """Return (and create) the avatar directory for a persona under data_root."""

    return Path(get_settings().data_root) / "persona" / persona / "avatar"


def _sample_model_path() -> Path:
    """Path to the bundled sample.vrm (repo-relative, from this file upward)."""
    return Path(__file__).resolve().parents[5] / "prototype" / "vrm-avatar" / "models" / "sample.vrm"


def _safe_model_name(name: str) -> str:
    """basename のみ受け、安全な文字（英数字/._-）以外を除去する。"""
    base = os.path.basename(name).replace("..", "").strip()
    return _SAFE_FILENAME.sub("", base)


# ── pure logic layer (_do_*) ───────────────────────────────────────


def _do_list_models(persona: str) -> dict:
    """List *.vrm files in the persona avatar dir (empty if missing)."""
    avatar_dir = _avatar_dir(persona)
    if not avatar_dir.is_dir():
        return {"models": [], "current": None}
    models = sorted(p.name for p in avatar_dir.glob("*.vrm") if p.is_file())
    return {"models": models, "current": None}


def _do_resolve_model(persona: str, name: str) -> dict | None:
    """Resolve a model file path. None → fall back to sample.vrm."""
    safe = _safe_model_name(name)
    if not safe or not safe.lower().endswith(".vrm"):
        return None
    path = _avatar_dir(persona) / safe
    if not path.is_file():
        return None
    return {"file_path": str(path), "filename": safe}


async def _do_save_model(persona: str, filename: str, file_bytes: bytes) -> dict:
    """Save an uploaded VRM model (overwrite allowed) and return metadata."""
    safe_name = _safe_model_name(filename)
    if not safe_name.lower().endswith(".vrm"):
        raise ValueError("only .vrm files are accepted")
    avatar_dir = _avatar_dir(persona)
    avatar_dir.mkdir(parents=True, exist_ok=True)
    dest = avatar_dir / safe_name
    dest.write_bytes(file_bytes)
    return {"filename": safe_name, "url": f"/api/chat/{persona}/avatar/model?name={safe_name}", "size": len(file_bytes)}


# ── HTTP adapter layer ─────────────────────────────────────────────


async def list_avatar_models(request: Request) -> JSONResponse:
    """GET /api/chat/{persona}/avatar/models — list uploaded VRM models."""
    persona, ctx = _resolve_request(request)
    if not ctx or not _PERSONA_PATTERN.match(persona):
        return JSONResponse({"error": "Persona not found"}, status_code=404)
    return JSONResponse(_do_list_models(persona))


async def serve_avatar_model(request: Request) -> Response:
    """GET /api/chat/{persona}/avatar/model?name=<filename> — serve a VRM model.

    name 未指定 or 該当ファイル無し → 同梱 sample.vrm を配信（初期フォールバック）。
    """
    from starlette.responses import FileResponse

    persona, ctx = _resolve_request(request)
    if not ctx or not _PERSONA_PATTERN.match(persona):
        return JSONResponse({"error": "Persona not found"}, status_code=404)

    name = request.query_params.get("name", "")
    resolved = _do_resolve_model(persona, name)
    if resolved is None:
        path = _sample_model_path()
        if not path.is_file():
            return JSONResponse({"error": "No model available"}, status_code=404)
        return FileResponse(str(path), media_type="model/gltf-binary", filename="sample.vrm")
    return FileResponse(resolved["file_path"], media_type="model/gltf-binary", filename=resolved["filename"])


async def upload_avatar_model(request: Request) -> JSONResponse:
    """POST /api/chat/{persona}/avatar/model — multipart upload of a .vrm file."""
    from starlette.datastructures import UploadFile  # noqa: TC002

    persona, ctx = _resolve_request(request)
    if not ctx or not _PERSONA_PATTERN.match(persona):
        return JSONResponse({"error": "Persona not found"}, status_code=404)

    form = await request.form()
    upload = form.get("file")
    if not isinstance(upload, UploadFile) or not upload:
        return JSONResponse({"error": "file field required"}, status_code=400)

    filename = upload.filename or ""
    if not filename.lower().endswith(".vrm"):
        return JSONResponse({"error": "only .vrm files are accepted"}, status_code=400)

    file_bytes = await upload.read()
    if len(file_bytes) > _MAX_VRM_BYTES:
        return JSONResponse({"error": "file too large (max 100MB)"}, status_code=413)

    try:
        result = await _do_save_model(persona, filename, file_bytes)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    except OSError:
        logger.exception("upload_avatar_model: write failed for persona=%s", persona)
        return JSONResponse({"error": "Failed to save model"}, status_code=500)
    return JSONResponse(result)
