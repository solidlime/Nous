from __future__ import annotations

from typing import Any

import httpx

from .base import GeneratedImage, ImageGenProvider


class StabilityProvider(ImageGenProvider):
    def __init__(self, api_url: str) -> None:
        # api_url例: "http://localhost:7860"
        self._api_url = api_url.rstrip("/")

    @property
    def provider_name(self) -> str:
        return "stability"

    async def generate(
        self,
        prompt: str,
        size: str = "1024x1024",
        quality: str = "standard",
        n: int = 1,
        reference_image: bytes | None = None,
        **kwargs: Any,
    ) -> list[GeneratedImage]:
        # サイズ文字列を width x height にパース
        if "x" in size:
            parts = size.split("x")
            width, height = int(parts[0]), int(parts[1])
        else:
            width = height = 512  # デフォルト

        async with httpx.AsyncClient(timeout=120.0) as http:
            images: list[GeneratedImage] = []
            for _ in range(n):
                payload = {
                    "prompt": prompt,
                    "negative_prompt": "",
                    "steps": 20,
                    "width": width,
                    "height": height,
                    "cfg_scale": 7,
                    "sampler_name": "Euler a",
                }
                resp = await http.post(f"{self._api_url}/sdapi/v1/txt2img", json=payload)
                resp.raise_for_status()
                data = resp.json()

                # SD WebUIは "images" キーにbase64のリストを返す
                for img_b64 in data.get("images", []):
                    images.append(
                        GeneratedImage(
                            base64=img_b64,
                            revised_prompt=prompt,
                            size=f"{width}x{height}",
                        )
                    )
            return images
