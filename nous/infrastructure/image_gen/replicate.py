from __future__ import annotations

import asyncio
import base64
from typing import Any

import httpx

from .base import GeneratedImage, ImageGenProvider


class ReplicateProvider(ImageGenProvider):
    """Replicate API (FLUX Schnell) 画像生成プロバイダ"""

    def __init__(self, model: str, api_key: str) -> None:
        self._model = model
        self._api_key = api_key
        self._base_url = "https://api.replicate.com/v1"

    @property
    def provider_name(self) -> str:
        return "replicate"

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
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "Prefer": "wait",
        }

        aspect_ratio = self._size_to_aspect_ratio(size)

        async with httpx.AsyncClient(timeout=30.0) as client:
            # POST /v1/models/{owner}/{model}/predictions
            url = f"{self._base_url}/models/{self._model}/predictions"
            payload = {
                "input": {
                    "prompt": prompt,
                    "num_outputs": n,
                    "aspect_ratio": aspect_ratio,
                }
            }
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            prediction = resp.json()

            prediction_id = prediction.get("id")
            if not prediction_id:
                raise RuntimeError(f"Replicate: no prediction id in response: {prediction}")

            # Polling: 指数バックオフ
            status = prediction.get("status", "starting")
            poll_url = f"{self._base_url}/predictions/{prediction_id}"
            delay = 1.0
            max_delay = 10.0
            timeout = 30.0
            elapsed = 0.0

            while status in ("starting", "processing") and elapsed < timeout:
                await asyncio.sleep(delay)
                elapsed += delay
                delay = min(delay * 2, max_delay)

                poll_resp = await client.get(poll_url, headers=headers)
                poll_resp.raise_for_status()
                prediction = poll_resp.json()
                status = prediction.get("status", "")

            if status == "succeeded":
                output = prediction.get("output")
            elif status == "failed":
                error = prediction.get("error", "unknown error")
                raise RuntimeError(f"Replicate prediction failed: {error}")
            else:
                raise RuntimeError(f"Replicate prediction timed out (status={status})")

            if not output:
                raise RuntimeError("Replicate: no output in successful prediction")

            # output: URL文字列 or URL配列
            if isinstance(output, str):
                output_urls = [output]
            elif isinstance(output, list):
                output_urls = [u for u in output if isinstance(u, str)]
            else:
                output_urls = []

            images: list[GeneratedImage] = []
            for url_str in output_urls:
                img_resp = await client.get(url_str)
                img_resp.raise_for_status()
                img_base64 = base64.b64encode(img_resp.content).decode("utf-8")
                images.append(
                    GeneratedImage(
                        base64=img_base64,
                        revised_prompt=prompt,
                        size=size,
                    )
                )

            return images

    @staticmethod
    def _size_to_aspect_ratio(size: str) -> str:
        """サイズ文字列 ('1024x1024') をアスペクト比 ('1:1') に変換"""
        mapping: dict[str, str] = {
            "1024x1024": "1:1",
            "1792x1024": "16:9",
            "1024x1792": "9:16",
            "512x512": "1:1",
            "768x768": "1:1",
        }
        return mapping.get(size, "1:1")
