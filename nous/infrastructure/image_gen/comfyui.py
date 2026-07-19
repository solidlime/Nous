from __future__ import annotations

import asyncio
import base64
import random
import time
from typing import Any

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

    def __init__(
        self,
        api_url: str = "http://localhost:8188",
        checkpoint: str = "noobaiXLNAIXL_epsilonPred11Version.safetensors",
        loras: list[dict] | None = None,
        speed_lora_path: str = "",
        speed_lora_weight: float = 1.0,
        speed_lora_method: str = "",
        width: int = 1024,
        height: int = 1024,
        steps: int = 28,
        cfg: float = 5.5,
        sampler: str = "euler_ancestral",
        scheduler: str = "normal",
        seed: int = 0,
        denoise: float = 0.7,
    ) -> None:
        self._api_url = api_url.rstrip("/")
        self._checkpoint = checkpoint
        self._loras = loras or []
        self._speed_lora_path = speed_lora_path
        self._speed_lora_weight = speed_lora_weight
        self._speed_lora_method = speed_lora_method
        self._width = width
        self._height = height
        self._steps = steps
        self._cfg = cfg
        self._sampler = sampler
        self._scheduler = scheduler
        self._seed = seed
        self._denoise = denoise
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
                prompt_id = resp.json()["prompt_id"]
                if not isinstance(prompt_id, str):
                    raise RuntimeError(f"ComfyUI returned non-string prompt_id: {type(prompt_id)}")
                return prompt_id
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
        """ワークフロー JSON を構築（パラメータ駆動）。

        ノードID固定:
          4=CheckpointLoaderSimple, 3=KSampler, 5=EmptyLatentImage,
          6=CLIPTextEncode(pos), 7=CLIPTextEncode(neg),
          8=VAEDecode, 9=SaveImage, 10=VAEEncode, 11=LoadImage

        LoRA ノードID: 12 から動的採番。

        image_filename が指定された場合、img2img ワークフロー
        （LoadImage → VAEEncode → KSampler(denoise<1.0)）を使用。
        """
        # ── seed: 0 はランダム ──
        seed = self._seed if self._seed != 0 else random.randint(0, 2**63 - 1)

        # ── 高速化 LoRA の自動オーバーライド ──
        sampler = self._sampler
        cfg = self._cfg
        scheduler = self._scheduler
        if self._speed_lora_path and self._speed_lora_method:
            if self._speed_lora_method == "lcm":
                sampler = "lcm"
                cfg = 1.5
                scheduler = "sgm_uniform"
            elif self._speed_lora_method == "lightning":
                sampler = "euler"
                cfg = 0.0
                scheduler = "sgm_uniform"
            elif self._speed_lora_method == "hyper":
                sampler = "euler"
                cfg = 5.0
                scheduler = "sgm_uniform"
            elif self._speed_lora_method == "tcd":
                sampler = "euler_ancestral"
                cfg = 1.0
                scheduler = "normal"

        # ── 1. CheckpointLoaderSimple (4) ──
        nodes: dict[str, Any] = {
            "4": {
                "class_type": "CheckpointLoaderSimple",
                "inputs": {"ckpt_name": self._checkpoint},
            },
        }

        # ── 2. LoRA ノード (12, 13, ...) ──
        # model/clip 連鎖: Checkpoint → LoraLoader → LoraLoader → ...
        last_model_id: str = "4"
        last_clip_id: str = "4"
        next_id = 12

        # キャラ LoRA
        for lora in self._loras:
            path = lora.get("path", "")
            weight = lora.get("weight", 1.0)
            if not path:
                continue
            node_id = str(next_id)
            nodes[node_id] = {
                "class_type": "LoraLoader",
                "inputs": {
                    "model": [last_model_id, 0],
                    "clip": [last_clip_id, 1],
                    "lora_name": path,
                    "strength_model": weight,
                    "strength_clip": weight,
                },
            }
            last_model_id = node_id
            last_clip_id = node_id
            next_id += 1

        # 高速化 LoRA
        if self._speed_lora_path:
            node_id = str(next_id)
            nodes[node_id] = {
                "class_type": "LoraLoader",
                "inputs": {
                    "model": [last_model_id, 0],
                    "clip": [last_clip_id, 1],
                    "lora_name": self._speed_lora_path,
                    "strength_model": self._speed_lora_weight,
                    "strength_clip": self._speed_lora_weight,
                },
            }
            last_model_id = node_id
            next_id += 1

        # ── 3. EmptyLatentImage (5) / VAEEncode(10)+LoadImage(11) ──
        if image_filename:
            nodes["10"] = {
                "class_type": "VAEEncode",
                "inputs": {"pixels": ["11", 0], "vae": ["4", 2]},
            }
            nodes["11"] = {
                "class_type": "LoadImage",
                "inputs": {"image": image_filename},
            }
            latent_image: list[str | int] = ["10", 0]
            denoise = self._denoise
        else:
            nodes["5"] = {
                "class_type": "EmptyLatentImage",
                "inputs": {
                    "width": self._width,
                    "height": self._height,
                    "batch_size": n,
                },
            }
            latent_image = ["5", 0]
            denoise = 1.0

        # ── 4. CLIPTextEncode (6, 7) — clip は Checkpoint から直接 ──
        nodes["6"] = {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": prompt, "clip": ["4", 1]},
        }
        nodes["7"] = {
            "class_type": "CLIPTextEncode",
            "inputs": {
                "text": "lowres, bad anatomy, bad hands, text, error",
                "clip": ["4", 1],
            },
        }

        # ── 5. KSampler (3) — model は最後の LoRA または Checkpoint ──
        nodes["3"] = {
            "class_type": "KSampler",
            "inputs": {
                "seed": seed,
                "steps": self._steps,
                "cfg": cfg,
                "sampler_name": sampler,
                "scheduler": scheduler,
                "denoise": denoise,
                "model": [last_model_id, 0],
                "positive": ["6", 0],
                "negative": ["7", 0],
                "latent_image": latent_image,
            },
        }

        # ── 6. VAEDecode (8) + SaveImage (9) ──
        nodes["8"] = {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["3", 0], "vae": ["4", 2]},
        }
        nodes["9"] = {
            "class_type": "SaveImage",
            "inputs": {"filename_prefix": "nous_comfyui", "images": ["8", 0]},
        }

        return nodes
