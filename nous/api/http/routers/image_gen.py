from __future__ import annotations

import json
from typing import TYPE_CHECKING

from starlette.responses import JSONResponse

from nous.api.http.deps import _resolve_persona_from_request, _safe_get_context
from nous.infrastructure.image_gen.health import ImageGenHealthChecker
from nous.infrastructure.logging.structured import get_logger

if TYPE_CHECKING:
    from starlette.requests import Request

logger = get_logger(__name__)


def register_image_gen_routes(mcp) -> None:

    @mcp.custom_route("/api/image-gen/health", methods=["GET"])
    async def check_image_gen_health(request: Request) -> JSONResponse:
        """ComfyUI 接続確認 (GET /api/image-gen/health?url=http://...)"""
        url = request.query_params.get("url", "")
        if not url:
            return JSONResponse({"healthy": False, "error": "url query parameter required"}, status_code=400)

        checker = ImageGenHealthChecker(url)
        healthy = await checker.check()
        return JSONResponse(
            {
                "healthy": healthy,
                "url": url,
                "message": "ComfyUI is reachable" if healthy else "ComfyUI is unreachable",
            }
        )

    @mcp.custom_route("/api/chat/{persona}/image-gen/test", methods=["POST"])
    async def test_image_gen(request: Request) -> JSONResponse:
        """画像生成テストエンドポイント (POST /api/chat/{persona}/image-gen/test)"""
        persona = _resolve_persona_from_request(request)
        ctx = _safe_get_context(persona)
        if not ctx:
            return JSONResponse({"error": "Persona not found"}, status_code=404)

        try:
            body = await request.json()
        except (json.JSONDecodeError, TypeError):
            return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

        from nous.config.settings import get_settings
        from nous.domain.chat_config import ChatConfigFileRepository
        from nous.infrastructure.image_gen.comfyui import ComfyUIProvider

        repo = ChatConfigFileRepository(get_settings().data_root)
        config = repo.get(persona)

        if not config or not getattr(config, "image_gen_enabled", False):
            return JSONResponse({"error": "Image generation is disabled"}, status_code=400)

        prompt = body.get("prompt", "").strip()
        comfyui_url = getattr(config, "image_gen_comfyui_url", "") or body.get("comfyui_url", "http://localhost:8188")

        provider = ComfyUIProvider(
            api_url=comfyui_url,
            width=body.get("width", getattr(config, "image_gen_comfyui_width", 1024)),
            height=body.get("height", getattr(config, "image_gen_comfyui_height", 1024)),
            workflow_template=getattr(config, "image_gen_comfyui_workflow_template", ""),
            workflow_source=getattr(config, "image_gen_comfyui_workflow_source", "local"),
            workflow_name=getattr(config, "image_gen_comfyui_workflow_name", ""),
            timeout_seconds=getattr(config, "image_gen_comfyui_timeout_seconds", 180),
        )

        # ── i2i（固定）: 参照画像 reference.png を常時読み込む（無ければ 400）──
        from pathlib import Path as _Path
        _settings = get_settings()
        ref_path = _Path(_settings.data_root) / "persona" / persona / "images" / "reference.png"
        if not ref_path.exists():
            return JSONResponse({"error": f"参照画像がありません: {ref_path}"}, status_code=400)
        reference_image = ref_path.read_bytes()

        try:
            generated = await provider.generate(
                prompt=prompt,
                size=f"{body.get('width', 1024)}x{body.get('height', 1024)}",
                quality="standard",
                n=1,
                negative_prompt=body.get("negative_prompt") or getattr(config, "image_gen_negative_prompt", "") or "",
                reference_image=reference_image,
            )
        except Exception:
            return JSONResponse({"error": "Image generation failed"}, status_code=500)

        if not generated:
            return JSONResponse({"error": "No images generated"}, status_code=500)

        return JSONResponse(
            {
                "ok": True,
                "images": [
                    {
                        "base64": generated[0].base64,
                        "revised_prompt": generated[0].revised_prompt,
                        "size": generated[0].size,
                        "node_id": generated[0].node_id,
                        "node_title": generated[0].node_title,
                    }
                ],
            }
        )

    @mcp.custom_route("/api/chat/{persona}/image-gen/reference", methods=["POST"])
    async def upload_reference_image(request: Request) -> JSONResponse:
        """参照画像アップロード (i2i用) — POST multipart/form-data, field 'file'"""
        persona = _resolve_persona_from_request(request)
        ctx = _safe_get_context(persona)
        if not ctx:
            return JSONResponse({"error": "Persona not found"}, status_code=404)

        try:
            form = await request.form()
        except Exception:
            return JSONResponse({"error": "Invalid form data"}, status_code=400)

        uploaded = form.get("file")
        if not uploaded or not hasattr(uploaded, "filename"):
            return JSONResponse({"error": "No file uploaded. Use multipart/form-data with field name 'file'."}, status_code=400)

        # Validate file type
        content_type = getattr(uploaded, "content_type", "") or ""
        if content_type and not content_type.startswith("image/"):
            return JSONResponse({"error": f"Invalid file type: {content_type}. Only images allowed."}, status_code=400)

        # Save as reference.png
        from pathlib import Path
        from nous.config.settings import get_settings

        settings = get_settings()
        images_dir = Path(settings.data_root) / "persona" / persona / "images"
        images_dir.mkdir(parents=True, exist_ok=True)

        ref_path = images_dir / "reference.png"
        content = await uploaded.read()
        ref_path.write_bytes(content)

        logger.info("Reference image uploaded for persona %s: %d bytes", persona, len(content))
        return JSONResponse({
            "ok": True,
            "filename": "reference.png",
            "size": len(content),
            "url": f"/api/chat/{persona}/persona/images/reference.png",
        })
