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

# NOUS:negative_prompt / {{negative_prompt}} の既定値（3重複していたため集約）
_DEFAULT_NEGATIVE_PROMPT = "lowres, bad anatomy, bad hands, text, error"


class ComfyUIProvider(ImageGenProvider):
    """ComfyUI REST API 経由の画像生成プロバイダ

    Fire-and-forget パターン:
      1. POST /prompt でワークフロー送信 → prompt_id 取得
      2. GET /history/{prompt_id} をポーリング → 出力画像を取得
      3. GET /view で画像ダウンロード → base64 エンコード

    i2i（参照画像ベース）のみ対応:
      - reference_image を渡すと ComfyUI にアップロードし NOUS:reference_image で利用
      - ワークフローは必ず workflow_template（API形式JSON）から読み込む
    """

    def __init__(
        self,
        api_url: str = "http://localhost:8188",
        checkpoint: str = "noobaiXLNAIXL_epsilonPred11Version.safetensors",
        loras: list[dict] | None = None,
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
        if not workflow_template:
            raise ValueError("workflow_template is required")
        self._api_url = api_url.rstrip("/")
        self._checkpoint = checkpoint
        self._loras = loras or []
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

        テンプレート必須: workflow_template の API形式JSON を読み込み、
        NOUS: タグ / レガシー {{placeholder}} を注入して送信する。
        参照画像はアップロードし NOUS:reference_image / {{reference_image}} で利用。
        """
        image_filename: str | None = None
        if reference_image is not None:
            image_filename = await self._upload_reference_image(reference_image)

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
        seed = self._seed if self._seed != 0 else random.randint(1, 2**63 - 1)

        # レガシー {{placeholder}} 置換（後方互換・プレースホルダがある場合のみ）
        if "{{" in template_json:
            template_json = template_json.replace("{{prompt}}", prompt)
            template_json = template_json.replace("{{negative_prompt}}", negative_prompt or _DEFAULT_NEGATIVE_PROMPT)
            template_json = template_json.replace("{{seed}}", str(seed))
            template_json = template_json.replace("{{width}}", str(self._width))
            template_json = template_json.replace("{{height}}", str(self._height))
            template_json = template_json.replace("{{reference_image}}", image_filename or "")

        workflow = _json.loads(template_json)

        # node_id(str) → _meta.title（空なら省略）
        node_titles: dict[str, str] = {}
        try:
            for nid, node in workflow.items():
                title = (node.get("_meta") or {}).get("title")
                if title:
                    node_titles[str(nid)] = str(title)
        except Exception:
            pass

        # NOUS:display タグ: 表示対象ノードIDの収集（タイトルが完全一致のみ・前後空白許容）
        display_node_ids: set[str] = set()
        try:
            for nid, node in workflow.items():
                title = (node.get("_meta") or {}).get("title")
                if title and str(title).strip() == "NOUS:display":
                    display_node_ids.add(str(nid))
        except Exception:
            pass

        # NOUS: タグ注入（ノードの _meta.title ベース）
        workflow = self._apply_nous_injections(
            workflow,
            prompt=prompt,
            negative_prompt=negative_prompt,
            image_filename=image_filename,
            seed=seed,
        )

        # POST /prompt — 最大 2 回リトライ
        prompt_id = await self._submit_workflow(workflow)

        # Poll /history — 最大 180 秒
        return await self._poll_result(
            prompt_id,
            prompt,
            size,
            n,
            negative_prompt=negative_prompt,
            node_titles=node_titles,
            display_node_ids=display_node_ids or None,  # 空集合は None（フィルタ無効・全表示）
        )

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

        # 単純なキー注入（LoRA 以外。display は表示フィルタ用なので注入対象外）
        for _, node, tag in tagged:
            key = tag[len("NOUS:"):]
            if key not in ("lora", "display"):
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
        class_type = node.get("class_type", "")
        # INTConstant / FloatConstant ノードは value フィールドしか持たない。
        # 数値系タグは value へ（int/float に型合わせして）注入する。
        if class_type in ("INTConstant", "FloatConstant"):
            if key == "seed":
                inputs["value"] = int(seed)  # value のみ（noise_seed フィールドは無い）
                return
            if key == "width":
                inputs["value"] = int(self._width)
                return
            if key == "height":
                inputs["value"] = int(self._height)
                return
            if key == "steps":
                inputs["value"] = int(self._steps)
                return
            if key == "cfg":
                inputs["value"] = float(self._cfg)
                return
            if key == "denoise":
                inputs["value"] = float(self._denoise)
                return
            # 数値系以外（prompt / sampler 等）は従来のセマンティックフィールドへフォールスルー

        if key == "prompt":
            inputs["text"] = prompt
        elif key == "negative_prompt":
            inputs["text"] = negative_prompt or _DEFAULT_NEGATIVE_PROMPT
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
        """rgthree Power Lora Loader の lora_1..lora_5 スロットへ注入する。

        rgthree はオブジェクト形式のみ認識する:
        {"on": True, "lora": "<filename>", "strength": <weight>}
        未使用スロットは "" （rgthree のゲートがスキップする）。
        """
        inputs = node.setdefault("inputs", {})
        for i in range(1, 6):
            slot = f"lora_{i}"
            if i <= len(loras):
                lora = loras[i - 1]
                inputs[slot] = {
                    "on": True,
                    "lora": lora["path"],
                    "strength": lora["weight"],
                }
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

    async def _poll_result(
        self,
        prompt_id: str,
        prompt: str,
        size: str,
        n: int,
        negative_prompt: str = "",
        node_titles: dict[str, str] | None = None,
        display_node_ids: set[str] | None = None,
    ) -> list[GeneratedImage]:
        """履歴をポーリングして生成画像を取得（最大 60 回 × 3s = 180s）。

        display_node_ids が None の場合は全画像 display=True（後方互換）。
        """
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
            if not outputs:
                continue

            # NOUS:display 指定ノードが出力画像を一切生成しなかった場合は
            # 全画像を表示にフォールバック（黙って全部捨てる事故を防ぐ）
            fallback_all = False
            if display_node_ids and not any(str(nid) in display_node_ids for nid in outputs):
                logger.warning(
                    "NOUS:display ノード %s が出力画像を生成しなかったため全画像を表示します",
                    sorted(display_node_ids),
                )
                fallback_all = True

            images: list[GeneratedImage] = []
            for node_id, output in outputs.items():
                for img in output.get("images", []):
                    try:
                        img_resp = await self.client.get(
                            f"{self._api_url}/view",
                            params={"filename": img["filename"], "type": "output"},
                        )
                        img_resp.raise_for_status()
                        b64 = base64.b64encode(img_resp.content).decode("utf-8")
                        nid = str(node_id)
                        images.append(
                            GeneratedImage(
                                base64=b64,
                                revised_prompt=prompt,
                                size=size,
                                negative_prompt=negative_prompt,
                                node_id=nid,
                                node_title=(node_titles or {}).get(nid),
                                display=fallback_all or display_node_ids is None or nid in display_node_ids,
                            )
                        )
                    except Exception:
                        continue
            if images:
                return images[:n]

        raise RuntimeError("ComfyUI generation timed out after 180s")
