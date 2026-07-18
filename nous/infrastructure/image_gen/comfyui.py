from __future__ import annotations

import asyncio
import base64
import time
from typing import Any, cast

import httpx

from .base import GeneratedImage, ImageGenProvider


class ComfyUIProvider(ImageGenProvider):
    """ComfyUI REST API 経由の画像生成プロバイダ

    Fire-and-forget パターン:
      1. POST /prompt でワークフロー送信 → prompt_id 取得
      2. GET /history/{prompt_id} をポーリング → 出力画像を取得
      3. GET /view で画像ダウンロード → base64 エンコード

    img2img サポート:
      - reference_image を渡すと ComfyUI にアップロードし img2img ワークフローを構築
    """

    def __init__(self, api_url: str = "http://localhost:8188") -> None:
        self._api_url = api_url.rstrip("/")
        self._client: httpx.AsyncClient | None = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(connect=5.0, read=180.0, write=180.0, pool=5.0))
        return self._client

    @property
    def provider_name(self) -> str:
        return "comfyui"

    async def health_check(self) -> bool:
        """ComfyUI のヘルスチェック: GET /system_stats"""
        try:
            r = await self.client.get(f"{self._api_url}/system_stats")
            return r.status_code == 200
        except Exception:
            return False

    async def generate(
        self,
        prompt: str,
        size: str = "512x512",
        quality: str = "standard",
        n: int = 1,
        reference_image: bytes | None = None,
        **kwargs: Any,
    ) -> list[GeneratedImage]:
        """ComfyUI で画像生成（fire-and-forget + polling）

        reference_image が指定された場合、img2img ワークフローを使用。
        """
        image_filename: str | None = None
        if reference_image is not None:
            image_filename = await self._upload_reference_image(reference_image)

        workflow = self._build_workflow(prompt, size, n, image_filename=image_filename)

        # POST /prompt — 最大 2 回リトライ
        prompt_id = await self._submit_workflow(workflow)

        # Poll /history — 最大 180 秒
        return await self._poll_result(prompt_id, prompt, size, n)

    async def _upload_reference_image(self, image_bytes: bytes) -> str:
        """参照画像を ComfyUI の /upload/image にアップロードし、filename を返す。"""
        filename = f"nous_ref_{int(time.time() * 1000)}.png"
        files: dict[str, tuple[str | None, str | bytes, str | None]] = {
            "image": (filename, image_bytes, "image/png"),
            "type": (None, "input", None),
            "overwrite": (None, "True", None),
        }
        resp = await self.client.post(f"{self._api_url}/upload/image", files=files)
        resp.raise_for_status()
        return filename

    async def _submit_workflow(self, workflow: dict) -> str:
        """ワークフローを送信し prompt_id を取得。接続エラー時は最大2回リトライ。"""
        last_exc: Exception | None = None
        for attempt in range(3):  # 初回 + 2 リトライ
            try:
                resp = await self.client.post(f"{self._api_url}/prompt", json={"prompt": workflow})
                resp.raise_for_status()
                return cast(str, resp.json()["prompt_id"])
            except (httpx.ConnectError, httpx.TimeoutException) as e:
                last_exc = e
                if attempt < 2:
                    await asyncio.sleep(1.0)
                    continue
        raise RuntimeError("ComfyUI generation failed after retries") from last_exc

    async def _poll_result(self, prompt_id: str, prompt: str, size: str, n: int) -> list[GeneratedImage]:
        """履歴をポーリングして生成画像を取得（最大 60 回 × 3s = 180s）。"""
        for _ in range(60):
            await asyncio.sleep(3)
            try:
                hist_resp = await self.client.get(f"{self._api_url}/history/{prompt_id}")
                hist = hist_resp.json()
            except Exception:
                continue

            if prompt_id not in hist:
                continue

            outputs = hist[prompt_id].get("outputs", {})
            images: list[GeneratedImage] = []
            for _node_id, output in outputs.items():
                for img in output.get("images", []):
                    try:
                        img_resp = await self.client.get(
                            f"{self._api_url}/view",
                            params={"filename": img["filename"], "type": "output"},
                        )
                        img_resp.raise_for_status()
                        b64 = base64.b64encode(img_resp.content).decode("utf-8")
                        images.append(GeneratedImage(base64=b64, revised_prompt=prompt, size=size))
                    except Exception:
                        continue
            if images:
                return images[:n]

        raise RuntimeError("ComfyUI generation timed out after 180s")

    def _build_workflow(self, prompt: str, size: str, n: int, image_filename: str | None = None) -> dict:
        """ワークフロー JSON を構築。

        image_filename が指定された場合、img2img ワークフロー
        （LoadImage → VAEEncode → KSampler(denoise<1.0)）を使用。
        指定がない場合、従来の txt2img（EmptyLatentImage）を使用。
        """
        if "x" in size:
            parts = size.split("x")
            w, h = int(parts[0]), int(parts[1])
        else:
            w = h = 512

        if image_filename:
            # ── img2img ワークフロー ────────────────────────────────
            return {
                "3": {
                    "class_type": "KSampler",
                    "inputs": {
                        "seed": 0,
                        "steps": 30,
                        "cfg": 5.0,
                        "sampler_name": "euler_ancestral",
                        "scheduler": "normal",
                        "denoise": 0.7,  # img2img: 元画像の特徴を残す
                        "model": ["4", 0],
                        "positive": ["6", 0],
                        "negative": ["7", 0],
                        "latent_image": ["10", 0],  # VAEEncode からの latent
                    },
                },
                "4": {
                    "class_type": "CheckpointLoaderSimple",
                    "inputs": {"ckpt_name": "animagine-xl-4.0.safetensors"},
                },
                "6": {
                    "class_type": "CLIPTextEncode",
                    "inputs": {"text": prompt, "clip": ["4", 1]},
                },
                "7": {
                    "class_type": "CLIPTextEncode",
                    "inputs": {
                        "text": "lowres, bad anatomy, bad hands, text, error",
                        "clip": ["4", 1],
                    },
                },
                "8": {
                    "class_type": "VAEDecode",
                    "inputs": {"samples": ["3", 0], "vae": ["4", 2]},
                },
                "9": {
                    "class_type": "SaveImage",
                    "inputs": {"filename_prefix": "nous_comfyui", "images": ["8", 0]},
                },
                "10": {
                    "class_type": "VAEEncode",
                    "inputs": {"pixels": ["11", 0], "vae": ["4", 2]},
                },
                "11": {
                    "class_type": "LoadImage",
                    "inputs": {"image": image_filename},
                },
            }
        else:
            # ── txt2img ワークフロー（従来） ────────────────────────
            return {
                "3": {
                    "class_type": "KSampler",
                    "inputs": {
                        "seed": 0,
                        "steps": 30,
                        "cfg": 5.0,
                        "sampler_name": "euler_ancestral",
                        "scheduler": "normal",
                        "denoise": 1.0,
                        "model": ["4", 0],
                        "positive": ["6", 0],
                        "negative": ["7", 0],
                        "latent_image": ["5", 0],
                    },
                },
                "4": {
                    "class_type": "CheckpointLoaderSimple",
                    "inputs": {"ckpt_name": "animagine-xl-4.0.safetensors"},
                },
                "5": {
                    "class_type": "EmptyLatentImage",
                    "inputs": {"width": w, "height": h, "batch_size": n},
                },
                "6": {
                    "class_type": "CLIPTextEncode",
                    "inputs": {"text": prompt, "clip": ["4", 1]},
                },
                "7": {
                    "class_type": "CLIPTextEncode",
                    "inputs": {
                        "text": "lowres, bad anatomy, bad hands, text, error",
                        "clip": ["4", 1],
                    },
                },
                "8": {
                    "class_type": "VAEDecode",
                    "inputs": {"samples": ["3", 0], "vae": ["4", 2]},
                },
                "9": {
                    "class_type": "SaveImage",
                    "inputs": {"filename_prefix": "nous_comfyui", "images": ["8", 0]},
                },
            }
