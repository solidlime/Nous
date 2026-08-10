from __future__ import annotations

import asyncio
import base64
import logging
import random
import time
from typing import Any

import httpx

from .base import GeneratedImage, ImageGenProvider
from .workflow_converter import WorkflowConversionError, apply_generation_params, convert_ui_to_api, is_api_format

logger = logging.getLogger(__name__)


class ComfyUIProvider(ImageGenProvider):
    """ComfyUI REST API 経由の画像生成プロバイダ

    Fire-and-forget パターン:
      1. POST /prompt でワークフロー送信 → prompt_id 取得
      2. GET /history/{prompt_id} をポーリング → 出力画像を取得
      3. GET /view で画像ダウンロード → base64 エンコード

    i2i（参照画像ベース）のみ対応:
      - reference_image を渡すと ComfyUI にアップロードし NOUS:reference_image で利用
      - ワークフローは workflow_source に応じて取得する:
        "local"（既定）: Nous 側のワークフローテンプレートファイル（API形式JSON）
        "comfyui": ComfyUI の /userdata API から UI 形式ワークフローを取得し変換
    """

    def __init__(
        self,
        api_url: str = "http://localhost:8188",
        width: int = 1024,
        height: int = 1024,
        workflow_template: str = "",
        workflow_source: str = "local",  # "local" | "comfyui"
        workflow_name: str = "",  # workflow_source="comfyui" 時: ComfyUI 側のワークフローファイル名
        object_info_cache_ttl: float = 300.0,
        timeout_seconds: float = 180.0,
    ) -> None:
        if workflow_source == "local":
            if not workflow_template:
                raise ValueError("workflow_template is required")
        else:
            if not workflow_name:
                raise ValueError("workflow_name is required when workflow_source='comfyui'")
        self._api_url = api_url.rstrip("/")
        # サイズは実行時注入用（preset 解決後の値。apply_generation_params が使う）
        self._width = width
        self._height = height
        self._workflow_template = workflow_template
        self._workflow_source = workflow_source
        self._workflow_name = workflow_name
        self._object_info_cache_ttl = object_info_cache_ttl
        self._object_info_cache: dict | None = None
        self._object_info_cache_time: float = 0.0
        self._timeout_seconds = timeout_seconds
        self._client: httpx.AsyncClient | None = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(
                    connect=5.0,
                    read=self._timeout_seconds,
                    write=self._timeout_seconds,
                    pool=5.0,
                )
            )
        return self._client

    @property
    def provider_name(self) -> str:
        return "comfyui"

    async def health_check(self) -> bool:
        """ComfyUI のヘルスチェック: GET /system_stats（専用ショートタイムアウト 5s）"""
        try:
            r = await self.client.get(
                f"{self._api_url}/system_stats",
                timeout=httpx.Timeout(connect=5.0, read=5.0, write=5.0, pool=5.0),
            )
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

        ワークフローは workflow_source に応じて取得する:
          - local: Nous 側のファイル（従来どおり）
          - comfyui: ComfyUI の /userdata API から UI 形式ワークフローを取得し変換
        取得後、apply_generation_params（サイズ・枚数・ランダムシード）を適用し、
        NOUS: タグ / レガシー {{placeholder}} を注入して送信する。
        """
        image_filename: str | None = None
        if reference_image is not None:
            image_filename = await self._upload_reference_image(reference_image)

        # シードは毎回ランダム（ユーザー決定）。タグ注入と seed ランダム化で共用。
        seed = random.randint(1, 2**63 - 1)
        workflow = await self._load_workflow(
            prompt=prompt,
            negative_prompt=negative_prompt,
            image_filename=image_filename,
            seed=seed,
        )
        # 保存時の固定 seed 対策＋サイズ・枚数の実行時注入（対応ノードが無ければ無変更）
        workflow = apply_generation_params(
            workflow, width=self._width, height=self._height, n=n, seed=seed
        )

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

        # Poll /history — 実時間タイムアウト（既定 180 秒）
        return await self._poll_result(
            prompt_id,
            prompt,
            size,
            n,
            negative_prompt=negative_prompt,
            node_titles=node_titles,
            display_node_ids=display_node_ids or None,  # 空集合は None（フィルタ無効・全表示）
        )

    async def _load_workflow(
        self,
        *,
        prompt: str,
        negative_prompt: str,
        image_filename: str | None,
        seed: int,
    ) -> dict:
        """ワークフローを取得して API 形式 dict で返す。

        - workflow_source="comfyui": /userdata API で UI 形式を取得 → 変換
        - workflow_source="local": 従来のファイル読込 + レガシー {{placeholder}} 置換
        """
        if self._workflow_source == "comfyui":
            ui_workflow = await self._fetch_userdata_workflow()
            if is_api_format(ui_workflow):
                return ui_workflow
            object_info = await self._get_object_info()
            return convert_ui_to_api(ui_workflow, object_info)

        # local: 従来のテンプレートファイル
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

        # レガシー {{placeholder}} 置換（後方互換・プレースホルダがある場合のみ）
        if "{{" in template_json:
            template_json = template_json.replace("{{prompt}}", prompt)
            template_json = template_json.replace("{{negative_prompt}}", negative_prompt)
            template_json = template_json.replace("{{seed}}", str(seed))
            template_json = template_json.replace("{{width}}", str(self._width))
            template_json = template_json.replace("{{height}}", str(self._height))
            template_json = template_json.replace("{{reference_image}}", image_filename or "")

        workflow = _json.loads(template_json)
        if is_api_format(workflow):
            return workflow
        # ローカルに置いた UI 形式テンプレートも変換で実行可能にする
        object_info = await self._get_object_info()
        return convert_ui_to_api(workflow, object_info)

    async def _fetch_userdata_workflow(self) -> dict:
        """ComfyUI /userdata API から保存済みワークフローを取得して dict で返す。

        GET /userdata/workflows/{name}.json（user/default 配下の相対パス）
        """
        import json as _json
        from urllib.parse import quote

        name = self._workflow_name
        if not name.endswith(".json"):
            name += ".json"
        # パストラバーサル防止: 単一ファイル名のみ許可
        if "/" in name or "\\" in name or name.startswith("."):
            raise ValueError(f"Invalid workflow name: {self._workflow_name!r}")

        resp = await self.client.get(f"{self._api_url}/userdata/workflows/{quote(name)}")
        if resp.status_code == 404:
            raise FileNotFoundError(
                f"Workflow not found on ComfyUI: workflows/{name} "
                "(GET /userdata?dir=workflows&recurse=true で一覧を確認)"
            )
        resp.raise_for_status()
        try:
            return _json.loads(resp.text)
        except _json.JSONDecodeError as e:
            raise WorkflowConversionError(f"Workflow file {name} is not valid JSON: {e}") from e

    async def _get_object_info(self) -> dict:
        """GET /object_info を TTL キャッシュ付きで取得する。"""
        now = time.monotonic()
        if (
            self._object_info_cache is not None
            and now - self._object_info_cache_time < self._object_info_cache_ttl
        ):
            return self._object_info_cache
        resp = await self.client.get(f"{self._api_url}/object_info")
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, dict):
            raise RuntimeError("ComfyUI /object_info returned unexpected data")
        self._object_info_cache = data
        self._object_info_cache_time = now
        return data

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

        ノードの _meta.title が "NOUS:key" の場合、対応する値をそのノードの inputs に
        書き込む。checkpoint / lora / steps / cfg / sampler / scheduler / denoise の
        タグは廃止（パラメータはワークフロー側に一元化）: 未知タグとして warning のみ。
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

        for _, node, tag in tagged:
            key = tag[len("NOUS:"):]
            if key == "display":
                continue  # display は表示フィルタ用なので注入対象外
            self._inject_nous_key(
                node, key, prompt=prompt, negative_prompt=negative_prompt, image_filename=image_filename, seed=seed
            )

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
        if class_type in ("INTConstant", "FloatConstant"):
            if key == "seed":
                inputs["value"] = int(seed)  # 毎回ランダム（generate 側で計算）
                return
            if key == "width":
                inputs["value"] = int(self._width)
                return
            if key == "height":
                inputs["value"] = int(self._height)
                return

        if key == "prompt":
            inputs["text"] = prompt
        elif key == "negative_prompt":
            inputs["text"] = negative_prompt
        elif key == "reference_image":
            if not image_filename:
                raise ValueError("NOUS:reference_image タグが設定されていますが参照画像がありません")
            inputs["image"] = image_filename
        else:
            # 廃止タグ（checkpoint / lora / steps / cfg / sampler / scheduler / denoise）等
            logger.warning("Unknown NOUS tag ignored: NOUS:%s", key)

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
        """履歴をポーリングして生成画像を取得（実時間タイムアウト: timeout_seconds）。

        display_node_ids が None の場合は全画像 display=True（後方互換）。
        ComfyUI 実行エラー（status.status_str == "error"）は即時検出して raise する。
        """
        deadline = time.monotonic() + self._timeout_seconds
        while time.monotonic() < deadline:
            await asyncio.sleep(min(3.0, max(0.0, deadline - time.monotonic())))
            try:
                hist_resp = await self.client.get(f"{self._api_url}/history/{prompt_id}")
                hist = hist_resp.json()
            except Exception:
                continue

            if prompt_id not in hist:
                continue

            # ComfyUI 実行エラー: 出力が生成されないままポーリング継続せず即時検出
            status = hist[prompt_id].get("status", {})
            if status.get("status_str") == "error":
                messages = status.get("messages", [])
                if messages:
                    raise RuntimeError(f"ComfyUI generation failed: {messages}")
                raise RuntimeError("ComfyUI generation failed")

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

        raise RuntimeError(f"ComfyUI generation timed out after {self._timeout_seconds:.0f}s")
