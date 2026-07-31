from __future__ import annotations

import asyncio
import base64
import logging
import random
import time
from typing import Any

import httpx

from .base import GeneratedImage, ImageGenProvider

logger = logging.getLogger(__name__)


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
        workflow_template: str = "",
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
        self._workflow_template = workflow_template
        self._client: httpx.AsyncClient | None = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(connect=5.0, read=180.0, write=180.0, pool=5.0))
        return self._client

    @staticmethod
    def _normalize_lora_path(path: str) -> str:
        """ComfyUI の LoraLoader が要求する .safetensors 拡張子を補完する。"""
        if path and not path.endswith(".safetensors"):
            return path + ".safetensors"
        return path

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
        negative_prompt: str = "",
        **kwargs: Any,
    ) -> list[GeneratedImage]:
        """ComfyUI で画像生成（fire-and-forget + polling）

        reference_image が指定された場合:
          - テンプレートモード: 参照画像をアップロードし NOUS:reference_image / {{reference_image}} で利用
          - 動的ビルド: img2img ワークフローを構築
        """
        image_filename: str | None = None
        if reference_image is not None:
            image_filename = await self._upload_reference_image(reference_image)

        if self._workflow_template:
            # テンプレートモード: JSON読み込み → NOUSタグ注入 → そのまま送信
            import json as _json
            from pathlib import Path as _Path

            template_path = _Path(self._workflow_template)
            if not template_path.is_absolute():
                # 相対パスは Nous data_root からの相対
                from nous.config.settings import get_settings
                template_path = _Path(get_settings().data_root) / self._workflow_template

            if not template_path.exists():
                raise FileNotFoundError(f"Workflow template not found: {template_path}")

            template_json = template_path.read_text(encoding="utf-8")
            seed = self._seed if self._seed != 0 else random.randint(1, 2**31 - 1)

            # レガシー {{placeholder}} 置換（後方互換・プレースホルダがある場合のみ）
            if "{{" in template_json:
                template_json = template_json.replace("{{prompt}}", prompt)
                template_json = template_json.replace(
                    "{{negative_prompt}}", negative_prompt or "lowres, bad anatomy, bad hands, text, error"
                )
                template_json = template_json.replace("{{seed}}", str(seed))
                template_json = template_json.replace("{{width}}", str(self._width))
                template_json = template_json.replace("{{height}}", str(self._height))
                template_json = template_json.replace("{{reference_image}}", image_filename or "")

            workflow = _json.loads(template_json)

            # NOUS: タグ注入（ノードの _meta.title ベース）
            workflow = self._apply_nous_injections(
                workflow,
                prompt=prompt,
                negative_prompt=negative_prompt,
                image_filename=image_filename,
                seed=seed,
            )
        else:
            # 動的ビルドモード（従来通り）
            workflow = self._build_workflow(prompt, size, n, image_filename=image_filename, negative_prompt=negative_prompt)

        # POST /prompt — 最大 2 回リトライ
        prompt_id = await self._submit_workflow(workflow)

        # Poll /history — 最大 180 秒
        return await self._poll_result(prompt_id, prompt, size, n, negative_prompt=negative_prompt)

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

    def _apply_nous_injections(
        self,
        workflow: dict,
        *,
        prompt: str,
        negative_prompt: str,
        image_filename: str | None,
        seed: int,
    ) -> dict:
        """テンプレートワークフローへ NOUS: タグを注入する。

        ノードの _meta.title が "NOUS:key" の場合、対応する設定値をそのノードの
        inputs に書き込む。LoRA はグラフ再構成を伴うため最後に処理する。
        """
        tagged: list[tuple[Any, dict, str]] = []
        for node_id, node in workflow.items():
            if not isinstance(node, dict):
                continue
            meta = node.get("_meta")
            title = meta.get("title", "") if isinstance(meta, dict) else ""
            if isinstance(title, str) and title.strip().startswith("NOUS:"):
                tagged.append((node_id, node, title.strip()))

        if not tagged:
            return workflow

        # 単純なキー注入（LoRA 以外）
        for _, node, tag in tagged:
            key = tag[len("NOUS:"):]
            if key != "lora":
                self._inject_nous_key(
                    node, key, prompt=prompt, negative_prompt=negative_prompt, image_filename=image_filename, seed=seed
                )

        # LoRA 注入（グラフを再構成するため最後）
        for node_id, node, tag in tagged:
            key = tag[len("NOUS:"):]
            if key == "lora":
                self._inject_lora(workflow, node_id, node)

        return workflow

    def _inject_nous_key(
        self,
        node: dict,
        key: str,
        *,
        prompt: str,
        negative_prompt: str,
        image_filename: str | None,
        seed: int,
    ) -> None:
        inputs = node.setdefault("inputs", {})
        if key == "prompt":
            inputs["text"] = prompt
        elif key == "negative_prompt":
            inputs["text"] = negative_prompt or "lowres, bad anatomy, bad hands, text, error"
        elif key == "reference_image":
            if not image_filename:
                raise ValueError("NOUS:reference_image タグが設定されていますが参照画像がありません")
            inputs["image"] = image_filename
        elif key == "seed":
            inputs["seed"] = seed
            inputs["noise_seed"] = seed
        elif key == "width":
            inputs["width"] = self._width
        elif key == "height":
            inputs["height"] = self._height
        elif key == "steps":
            inputs["steps"] = self._steps
        elif key == "cfg":
            inputs["cfg"] = self._cfg
        elif key == "sampler":
            inputs["sampler_name"] = self._sampler
        elif key == "scheduler":
            inputs["scheduler"] = self._scheduler
        elif key == "denoise":
            inputs["denoise"] = self._denoise
        elif key == "checkpoint":
            inputs["ckpt_name"] = self._checkpoint
        else:
            logger.warning("Unknown NOUS tag ignored: NOUS:%s", key)

    def _inject_lora(self, workflow: dict, node_id: Any, node: dict) -> None:
        class_type = node.get("class_type", "")
        loras = [
            {"path": self._normalize_lora_path(lora.get("path", "")), "weight": lora.get("weight", 1.0)}
            for lora in self._loras
            if lora.get("path")
        ]
        if class_type == "LoraLoader":
            self._inject_lora_chain(workflow, node_id, node, loras)
        elif class_type == "Power Lora Loader":
            self._inject_power_lora(node, loras)
        else:
            logger.warning("NOUS:lora tag on unsupported class_type %r — skipped", class_type)

    def _inject_lora_chain(self, workflow: dict, node_id: Any, node: dict, loras: list[dict]) -> None:
        """標準 LoraLoader チェーン注入。タグ付きノードをチェーン先頭にする。"""
        if not loras:
            return  # 設定なし: ノードはそのまま
        inputs = node.setdefault("inputs", {})
        first = loras[0]
        inputs["lora_name"] = first["path"]
        inputs["strength_model"] = first["weight"]
        inputs["strength_clip"] = first["weight"]
        if len(loras) == 1:
            return

        # 後続 LoRA 用に一意な新規 ID を採番
        max_id = 0
        for nid in workflow:
            try:
                max_id = max(max_id, int(str(nid)))
            except (TypeError, ValueError):
                continue

        last_id = str(node_id)
        next_id = max_id + 1
        created: set[str] = set()
        for lora in loras[1:]:
            new_id = str(next_id)
            next_id += 1
            created.add(new_id)
            workflow[new_id] = {
                "class_type": "LoraLoader",
                "inputs": {
                    "model": [last_id, 0],
                    "clip": [last_id, 1],
                    "lora_name": lora["path"],
                    "strength_model": lora["weight"],
                    "strength_clip": lora["weight"],
                },
            }
            last_id = new_id

        # タグ付きノードの MODEL(0)/CLIP(1) 参照を最終チェーンノードへ張り替え
        # （新規チェーンノード自身は「前段ノード」を指すため対象外）
        tagged = str(node_id)
        for other_id, other in workflow.items():
            if str(other_id) == tagged or str(other_id) in created:
                continue
            if not isinstance(other, dict):
                continue
            other_inputs = other.get("inputs")
            if not isinstance(other_inputs, dict):
                continue
            for field, value in other_inputs.items():
                other_inputs[field] = self._remap_lora_ref(value, tagged, last_id)

    @staticmethod
    def _remap_lora_ref(value: Any, tagged_id: str, last_id: str) -> Any:
        """[node_id, output_index] 形式の参照を再帰的に張り替える（MODEL=0, CLIP=1 のみ）。"""
        if isinstance(value, list):
            if len(value) >= 2 and str(value[0]) == tagged_id:
                try:
                    if int(value[1]) in (0, 1):
                        return [last_id, value[1]]
                except (TypeError, ValueError):
                    pass
            return [ComfyUIProvider._remap_lora_ref(v, tagged_id, last_id) for v in value]
        return value

    def _inject_power_lora(self, node: dict, loras: list[dict]) -> None:
        """rgthree Power Lora Loader の lora_1..lora_5 スロットへ注入する。"""
        inputs = node.setdefault("inputs", {})
        for i in range(1, 6):
            slot = f"lora_{i}"
            if i <= len(loras):
                lora = loras[i - 1]
                inputs[slot] = [lora["path"], lora["weight"], lora["weight"]]
            else:
                inputs[slot] = ""

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

    async def _poll_result(self, prompt_id: str, prompt: str, size: str, n: int, negative_prompt: str = "") -> list[GeneratedImage]:
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
                        images.append(GeneratedImage(base64=b64, revised_prompt=prompt, size=size, negative_prompt=negative_prompt))
                    except Exception:
                        continue
            if images:
                return images[:n]

        raise RuntimeError("ComfyUI generation timed out after 180s")

    def _build_workflow(self, prompt: str, size: str, n: int, image_filename: str | None = None, negative_prompt: str = "") -> dict:
        """ワークフロー JSON を構築（パラメータ駆動）。

        ノードID固定:
            4=CheckpointLoaderSimple, 3=KSampler, 5=EmptyLatentImage,
            6=CLIPTextEncode(pos), 7=CLIPTextEncode(neg),
            8=VAEDecode, 9=SaveImage

        LoRA ノードID: 12 から動的採番。

        image_filename が指定された場合、LoadImage→VAEEncode→KSampler(denoise) の
        img2img ワークフローを使用。
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
            path = self._normalize_lora_path(lora.get("path", ""))
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
                    "lora_name": self._normalize_lora_path(self._speed_lora_path),
                    "strength_model": self._speed_lora_weight,
                    "strength_clip": self._speed_lora_weight,
                },
            }
            last_model_id = node_id
            next_id += 1

        # ── 3. Latent image ──
        if image_filename:
            # img2img: reference image → VAEEncode
            nodes["11"] = {
                "class_type": "LoadImage",
                "inputs": {"image": image_filename},
            }
            nodes["12"] = {
                "class_type": "VAEEncode",
                "inputs": {
                    "pixels": ["11", 0],
                    "vae": ["4", 2],
                },
            }
            latent_image: list[str | int] = ["12", 0]
            denoise = self._denoise
        else:
            # t2i: empty latent
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
                "text": negative_prompt or "lowres, bad anatomy, bad hands, text, error",
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
