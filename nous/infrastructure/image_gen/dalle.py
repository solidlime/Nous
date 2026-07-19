from __future__ import annotations

import base64
import os
from typing import Any

import httpx

from .base import GeneratedImage, ImageGenProvider


class DalleProvider(ImageGenProvider):
    def __init__(
        self, model: str = "dall-e-3", api_key: str = "", base_url: str = "", provider_name: str = "openai"
    ) -> None:
        self._model = model
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self._base_url = base_url
        self._provider_name = provider_name

    @property
    def provider_name(self) -> str:
        return self._provider_name

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
            raise ValueError(f"{self._provider_name} does not support reference_image (img2img)")
        from openai import AsyncOpenAI

        client_kwargs: dict = {"api_key": self._api_key}
        if self._base_url:
            client_kwargs["base_url"] = self._base_url
        client = AsyncOpenAI(**client_kwargs)

        # DALL-E 2 は quality パラメータ非対応
        gen_kwargs: dict = {"model": self._model, "prompt": prompt, "size": size, "n": n}
        if self._provider_name == "gemini":
            # Gemini accepts: auto | low | medium | high
            _gemini_quality_map = {"standard": "auto", "hd": "high"}
            gen_kwargs["quality"] = _gemini_quality_map.get(quality, quality)
        elif self._model not in ("dall-e-2",):
            gen_kwargs["quality"] = quality

        response = await client.images.generate(**gen_kwargs)

        images: list[GeneratedImage] = []
        async with httpx.AsyncClient() as http:
            for item in response.data:
                if item.url:
                    # URLから画像をダウンロードしてbase64化
                    resp = await http.get(item.url)
                    resp.raise_for_status()
                    img_base64 = base64.b64encode(resp.content).decode("utf-8")
                elif item.b64_json:
                    img_base64 = item.b64_json
                else:
                    continue

                images.append(
                    GeneratedImage(
                        base64=img_base64,
                        revised_prompt=item.revised_prompt if hasattr(item, "revised_prompt") else prompt,
                        size=size,
                    )
                )
        return images
