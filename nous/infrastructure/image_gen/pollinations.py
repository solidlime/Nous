from __future__ import annotations

import base64
from typing import Any
from urllib.parse import quote

import httpx

from .base import GeneratedImage, ImageGenProvider


class PollinationsImageProvider(ImageGenProvider):
    """Pollinations.ai — Free, no-API-key image generation."""

    @property
    def provider_name(self) -> str:
        return "pollinations"

    async def generate(
        self,
        prompt: str,
        size: str = "1024x1024",
        quality: str = "standard",
        n: int = 1,
        reference_image: bytes | None = None,
        **kwargs: Any,
    ) -> list[GeneratedImage]:
        if reference_image is not None:
            raise ValueError(f"{self.provider_name} does not support reference_image (img2img)")
        # Parse size
        if "x" in size:
            parts = size.split("x")
            width, height = int(parts[0]), int(parts[1])
        else:
            width = height = 1024

        # Clamp to max 1024 (Pollinations limit)
        width = min(width, 1024)
        height = min(height, 1024)

        encoded_prompt = quote(prompt)

        async with httpx.AsyncClient(timeout=30.0) as client:
            images: list[GeneratedImage] = []
            for _ in range(n):
                url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width={width}&height={height}&nologo=true"
                resp = await client.get(url)
                resp.raise_for_status()
                img_base64 = base64.b64encode(resp.content).decode("utf-8")
                images.append(
                    GeneratedImage(
                        base64=img_base64,
                        revised_prompt=prompt,
                        size=f"{width}x{height}",
                    )
                )
            return images
