from __future__ import annotations

import contextlib
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

        prompt = body.get("prompt", "test image: a cute anime girl").strip()
        comfyui_url = getattr(config, "image_gen_comfyui_url", "") or body.get("comfyui_url", "http://localhost:8188")

        # LoRA リスト: POST body 指定があれば優先、なければDB設定から
        if "loras" in body and isinstance(body["loras"], list):
            loras = body["loras"]
        else:
            loras_raw = getattr(config, "image_gen_comfyui_loras", "")
            loras: list[dict] = []
            if loras_raw:
                with contextlib.suppress(json.JSONDecodeError, TypeError):
                    loras = json.loads(loras_raw)

        provider = ComfyUIProvider(
            api_url=comfyui_url,
            checkpoint=getattr(
                config, "image_gen_comfyui_checkpoint", "noobaiXLNAIXL_epsilonPred11Version.safetensors"
            ),
            loras=loras,
            speed_lora_path=getattr(config, "image_gen_comfyui_speed_lora_path", ""),
            speed_lora_weight=getattr(config, "image_gen_comfyui_speed_lora_weight", 1.0),
            speed_lora_method=getattr(config, "image_gen_comfyui_speed_lora_method", ""),
            width=body.get("width", getattr(config, "image_gen_comfyui_width", 1024)),
            height=body.get("height", getattr(config, "image_gen_comfyui_height", 1024)),
            steps=body.get("steps", getattr(config, "image_gen_comfyui_steps", 28)),
            cfg=body.get("cfg", getattr(config, "image_gen_comfyui_cfg", 5.5)),
            sampler=body.get("sampler", getattr(config, "image_gen_comfyui_sampler", "euler_ancestral")),
            scheduler=body.get("scheduler", getattr(config, "image_gen_comfyui_scheduler", "normal")),
            seed=body.get("seed", getattr(config, "image_gen_comfyui_seed", 0)),
            denoise=body.get("denoise", getattr(config, "image_gen_comfyui_denoise", 0.7)),
        )

        try:
            generated = await provider.generate(
                prompt=prompt,
                size=f"{body.get('width', 1024)}x{body.get('height', 1024)}",
                quality="standard",
                n=1,
                negative_prompt=body.get("negative_prompt", ""),
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
                    }
                ],
            }
        )
