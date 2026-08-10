# Nous: ComfyUI保存ワークフロー直接実行（/userdata + UI→API変換）実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Nous の ComfyUI 画像生成を、Nous サーバーにワークフローファイルを置かなくても、ComfyUI 側（`D:\Application\ComfyUI\user\default\workflows\`）に保存済みの UI 形式ワークフローを `/userdata` API で取得し、`/object_info` を併用して API 形式に変換して実行できるようにする。あわせて、モデル/LoRA/steps/cfg 等のパラメータ注入を**廃止**し、画像生成の入力は「プロンプト（ポジティブ/ネガティブ）・参照画像・サイズ・枚数・ランダムシード」だけの最小インターフェースに絞る（モデル・LoRA・サンプリング設定はワークフロー側に一元化）。

**Architecture:** `nous/infrastructure/image_gen/workflow_converter.py` に UI形式→API形式変換の純関数（comfy-cli `workflow_to_api.py` の縮小移植）と、実行時パラメータ適用の `apply_generation_params()`（EmptyLatentImage へのサイズ/枚数注入＋seed ランダム化）を新設。`ComfyUIProvider` に `workflow_source`（`"local"` 従来 / `"comfyui"` 新規）と `workflow_name` を追加し、`"comfyui"` 時は GET `/userdata/workflows/{name}.json` → 変換（/object_info は TTL キャッシュ）→ `apply_generation_params` → NOUS:タグ注入 → POST /prompt の流れ。変換時に UI ノードの `title` を API 形式の `_meta.title` に写すことで、既存の NOUS: タグ注入機構（`NOUS:prompt` / `NOUS:negative_prompt` / `NOUS:reference_image` / `NOUS:width` / `NOUS:height` / `NOUS:seed` / `NOUS:display`）がそのまま機能する。

**Tech Stack:** Python 3.12, httpx（非同期）, pytest（asyncio_mode=auto）, pydantic（ToolConfig）。変更ファイルは Nous リポジトリ（github.com/solidlime/Nous）内。ローカルソースは無いため作業は一時 clone、実動確認は NAS デプロイ（\\nas\docker\nous）＋ローカル ComfyUI（D:\Application\ComfyUI 0.31.0）。

## Global Constraints

- 後方互換: `workflow_source` のデフォルトは `"local"`。local 時の `workflow_template` 必須チェック・レガシー `{{placeholder}}` 置換・参照画像アップロードは従来どおり維持。
- **パラメータ注入の廃止（本改訂の要）:** `image_gen_comfyui_checkpoint` / `_loras` / `_steps` / `_cfg` / `_sampler` / `_scheduler` / `_denoise` / `_seed` の設定、`NOUS:checkpoint` / `NOUS:lora` / `NOUS:steps` / `NOUS:cfg` / `NOUS:sampler` / `NOUS:scheduler` / `NOUS:denoise` タグ注入、LoRA チェーン注入（`_inject_lora` 系メソッド一式）を**削除**する。
- **維持する入力:** プロンプト（`NOUS:prompt`）・ネガティブ（`NOUS:negative_prompt`）・参照画像（`NOUS:reference_image`、i2i 固定）・サイズ（`NOUS:width` / `NOUS:height` タグと `apply_generation_params` の EmptyLatentImage 注入）・枚数 n=1〜4（batch_size 注入）・シード。
- **シードは毎回ランダム化（ユーザー決定）:** 保存済みワークフローの固定 seed 対策として、`apply_generation_params()` が `seed` / `noise_seed` 入力へ毎回ランダム値を注入する。`NOUS:seed` タグもランダム値注入に変更。
- 既存テスト43件のうち、廃止対象の注入機能を検証していたテスト（LoRA 注入系・パラメータタグ注入系）は**削除/書き換え**する（Task 2 Step 1 で明示）。
- 既存コード規約に従う: 遅延 import（`from ... import` は関数内）、`from __future__ import annotations`、line-length 120（ruff）、mypy strict は tests/ 除外。
- テストは既存パターン踏襲: `patch("httpx.AsyncClient")` + `AsyncMock(side_effect=[...])` + `patch("asyncio.sleep", new=AsyncMock(return_value=None))`。新規ワークフロー変換テストは純関数（HTTP モック不要）。
- 変換器は**縮小移植**: サブグラフ展開 / V3 dynamic combo / GetNode-SetNode / bypass パススルー は**対応外**（`# ponytail:` コメントで明記。必要になったら comfy-cli から移植）。
- 変換失敗は1ノードで全体を落とさない（comfy-cli と同じ try/except continue 方針）。
- セキュリティ: `/userdata` のファイル名は単一ファイル名のみ許可（`/` `\` `.` 先頭を拒否、トラバーサル対策）。
- コミットは各タスクの検証後に1回ずつ。

---

### Task 1: UI形式→API形式変換モジュール（workflow_converter.py）

**Files:**
- Create: `nous/infrastructure/image_gen/workflow_converter.py`
- Create: `tests/unit/workflow_fixtures.py`
- Create: `tests/unit/test_workflow_converter.py`

**Interfaces:**
- Produces（Task 2 が使用）:
  - `is_api_format(workflow: Any) -> bool` — API形式（`{node_id: {class_type, ...}}`）なら True
  - `convert_ui_to_api(workflow: dict, object_info: dict) -> dict` — UI形式→API形式。API形式が渡されたらそのまま返す
  - `WorkflowConversionError(Exception)` — nodes/links 欠落・object_info 不正時に送出
  - `apply_generation_params(workflow: dict, *, width: int, height: int, n: int, seed: int | None = None) -> dict` — 実行時パラメータ適用（Step 6 で追加）: EmptyLatentImage の width/height/batch_size 注入＋`seed`/`noise_seed` 入力（INT）のランダム化

- [ ] **Step 1: フィクスチャ作成（tests/unit/workflow_fixtures.py）**

```python
"""workflow_converter テスト用フィクスチャ。

Anima_T2I_Turbo_Aesthetic.json 相当の最小グラフ + /object_info の最小スキーマ。
"""

# 最小 UI 形式ワークフロー:
#   CLIPLoader(3) → CLIPTextEncode(6, title=NOUS:prompt) → KSampler(9)
#   ノード10 は Note（出力から除外されるべき）
#   ノード11 は muted (mode=2)（出力から除外されるべき）
MINI_UI_WORKFLOW = {
    "last_node_id": 11,
    "last_link_id": 2,
    "nodes": [
        {
            "id": 3,
            "type": "CLIPLoader",
            "title": "Load CLIP",
            "mode": 0,
            "inputs": [],
            "outputs": [{"name": "CLIP", "type": "CLIP", "links": [1]}],
            "widgets_values": ["qwen_3_06b_base.safetensors", "stable_diffusion", "default"],
        },
        {
            "id": 6,
            "type": "CLIPTextEncode",
            "title": "NOUS:prompt",
            "mode": 0,
            "inputs": [{"name": "clip", "type": "CLIP", "link": 1}],
            "outputs": [{"name": "CONDITIONING", "type": "CONDITIONING", "links": [2]}],
            "widgets_values": ["masterpiece, best quality, score_7, safe"],
        },
        {
            "id": 9,
            "type": "KSampler",
            "title": "KSampler",
            "mode": 0,
            "inputs": [
                {"name": "model", "type": "MODEL", "link": None},
                {"name": "positive", "type": "CONDITIONING", "link": 2},
                {"name": "negative", "type": "CONDITIONING", "link": None},
                {"name": "latent_image", "type": "LATENT", "link": None},
            ],
            "outputs": [{"name": "LATENT", "type": "LATENT", "links": []}],
            "widgets_values": [875817230929465, "randomize", 16, 1.0, "euler", "simple", 1.0],
        },
        {"id": 10, "type": "Note", "title": "memo", "mode": 0, "inputs": [], "outputs": [], "widgets_values": ["hello"]},
        {"id": 11, "type": "KSampler", "title": "muted", "mode": 2, "inputs": [], "outputs": [], "widgets_values": []},
    ],
    "links": [
        [1, 3, 0, 6, 0, "CLIP"],
        [2, 6, 0, 9, 1, "CONDITIONING"],
    ],
    "groups": [],
    "config": {},
    "extra": {},
    "version": 0.4,
}

# /object_info の最小スキーマ（実際の ComfyUI 応答の形に合わせる）
OBJECT_INFO = {
    "CLIPLoader": {
        "input": {
            "required": {
                "clip_name": ["STRING", {}],
                "type": [["stable_diffusion", "sdxl"], {}],
                "device": [["default", "cuda"], {}],
            },
            "optional": {},
        },
        "input_order": {"required": ["clip_name", "type", "device"], "optional": []},
        "display_name": "Load CLIP",
    },
    "CLIPTextEncode": {
        "input": {
            "required": {"clip": ["CLIP", {}], "text": ["STRING", {"multiline": True}]},
            "optional": {},
        },
        "input_order": {"required": ["clip", "text"], "optional": []},
        "display_name": "CLIP Text Encode (Prompt)",
    },
    "KSampler": {
        "input": {
            "required": {
                "model": ["MODEL", {}],
                "positive": ["CONDITIONING", {}],
                "negative": ["CONDITIONING", {}],
                "latent_image": ["LATENT", {}],
                "seed": ["INT", {}],
                "steps": ["INT", {"default": 20}],
                "cfg": ["FLOAT", {"default": 8.0}],
                "sampler_name": ["COMBO", {"options": ["euler", "euler_ancestral"]}],
                "scheduler": ["COMBO", {"options": ["normal", "simple", "karras"]}],
                "denoise": ["FLOAT", {"default": 1.0}],
            },
            "optional": {},
        },
        "input_order": {
            "required": [
                "model", "positive", "negative", "latent_image",
                "seed", "steps", "cfg", "sampler_name", "scheduler", "denoise",
            ],
            "optional": [],
        },
        "display_name": "KSampler",
    },
}
```

- [ ] **Step 2: テスト作成（tests/unit/test_workflow_converter.py）**

```python
"""workflow_converter の単体テスト（純関数・HTTP モック不要）"""

import json

import pytest

from nous.infrastructure.image_gen.workflow_converter import (
    WorkflowConversionError,
    convert_ui_to_api,
    is_api_format,
)
from tests.unit.workflow_fixtures import MINI_UI_WORKFLOW, OBJECT_INFO


def test_is_api_format_detects_api_dict():
    api = {"6": {"class_type": "CLIPTextEncode", "inputs": {"text": ""}}}
    assert is_api_format(api) is True


def test_is_api_format_rejects_ui_dict():
    assert is_api_format(MINI_UI_WORKFLOW) is False


def test_is_api_format_rejects_non_dict():
    assert is_api_format([1, 2, 3]) is False


def test_convert_basic_links_and_widgets():
    api = convert_ui_to_api(MINI_UI_WORKFLOW, OBJECT_INFO)
    assert api["6"]["class_type"] == "CLIPTextEncode"
    # リンク解決: link 1 = CLIPLoader(3) の出力スロット0
    assert api["6"]["inputs"]["clip"] == ["3", 0]
    assert api["6"]["inputs"]["text"] == "masterpiece, best quality, score_7, safe"
    # NOUS: タグ注入に必須の _meta.title（UI ノードの title から写す）
    assert api["6"]["_meta"]["title"] == "NOUS:prompt"
    assert api["3"]["_meta"]["title"] == "Load CLIP"


def test_convert_ksampler_widgets_and_control_marker():
    api = convert_ui_to_api(MINI_UI_WORKFLOW, OBJECT_INFO)
    inputs = api["9"]["inputs"]
    assert inputs["seed"] == 875817230929465
    assert "randomize" not in inputs.values()  # control_after_generate マーカーは除去
    assert inputs["steps"] == 16
    assert inputs["cfg"] == 1.0
    assert inputs["sampler_name"] == "euler"
    assert inputs["scheduler"] == "simple"
    assert inputs["denoise"] == 1.0
    assert inputs["positive"] == ["6", 0]


def test_convert_skips_note_and_muted_nodes():
    api = convert_ui_to_api(MINI_UI_WORKFLOW, OBJECT_INFO)
    assert "10" not in api  # Note
    assert "11" not in api  # muted (mode=2)


def test_convert_inlines_primitive_node_value():
    """PrimitiveNode は API 出力に含めず、値を接続先の入力へ直接埋め込む。"""
    wf = json.loads(json.dumps(MINI_UI_WORKFLOW))
    # KSampler(9) の model 入力（スロット0）を PrimitiveNode(20) に接続
    wf["nodes"][2]["inputs"][0]["link"] = 7
    wf["nodes"].append(
        {
            "id": 20,
            "type": "PrimitiveNode",
            "title": "model src",
            "mode": 0,
            "inputs": [],
            "outputs": [{"name": "MODEL", "type": "MODEL", "links": [7]}],
            "widgets_values": ["anima-aesthetic-v1.0.safetensors"],
        }
    )
    wf["links"].append([7, 20, 0, 9, 0, "MODEL"])
    api = convert_ui_to_api(wf, OBJECT_INFO)
    assert api["9"]["inputs"]["model"] == "anima-aesthetic-v1.0.safetensors"
    assert "20" not in api  # PrimitiveNode 自体は出力されない


def test_convert_strips_orphan_link_inputs():
    """存在しないノードを参照するリンク入力は削除される。"""
    wf = json.loads(json.dumps(MINI_UI_WORKFLOW))
    # KSampler(9) の model 入力を存在しないノード99へ接続
    wf["nodes"][2]["inputs"][0]["link"] = 8
    wf["links"].append([8, 99, 0, 9, 0, "MODEL"])
    api = convert_ui_to_api(wf, OBJECT_INFO)
    assert "model" not in api["9"]["inputs"]


def test_convert_accepts_api_format_input():
    api = {"6": {"class_type": "CLIPTextEncode", "inputs": {}}}
    assert convert_ui_to_api(api, OBJECT_INFO) is api


def test_convert_raises_without_nodes_list():
    with pytest.raises(WorkflowConversionError):
        convert_ui_to_api({"foo": "bar"}, OBJECT_INFO)


def test_convert_raises_without_object_info():
    with pytest.raises(WorkflowConversionError):
        convert_ui_to_api(MINI_UI_WORKFLOW, None)


def test_convert_missing_schema_node_is_skipped():
    """/object_info に無いノード型はスキップ（全体は落とさない）。"""
    wf = json.loads(json.dumps(MINI_UI_WORKFLOW))
    wf["nodes"].append({"id": 30, "type": "UnknownCustomNodeXYZ", "title": "x", "mode": 0, "inputs": [], "outputs": [], "widgets_values": [1]})
    api = convert_ui_to_api(wf, OBJECT_INFO)
    assert "30" not in api
    assert "6" in api
```

- [ ] **Step 3: テストを実行して失敗を確認**

Run: `python -m pytest tests/unit/test_workflow_converter.py -v`
Expected: FAIL — `ModuleNotFoundError: nous.infrastructure.image_gen.workflow_converter`

- [ ] **Step 4: 変換モジュール実装（nous/infrastructure/image_gen/workflow_converter.py）**

```python
"""ComfyUI UI形式ワークフロー（nodes/links）→ API形式（POST /prompt）変換。

comfy-cli の workflow_to_api.py を Nous 用に縮小移植したもの。
- widgets_values は /object_info のスキーマ（required+optional の順）と位置対応させる
- UI ノードの title を API 形式の _meta.title に写す（NOUS: タグ注入がこれを読む）
- 対応外（ponytail: 現状の Nous 利用ワークフローに不要。
  必要になったら comfy-cli から移植）:
  サブグラフ展開 / V3 dynamic combo 展開 / GetNode-SetNode トレース / bypass パススルー
"""

from __future__ import annotations

import copy
from typing import Any

# litegraph のノード mode。2=ミュート（実行しない）、4=バイパス（入力を素通し）
_MODE_MUTED = 2
_MODE_BYPASS = 4

# UI 専用ノード（API 形式に出力されない）
_UI_ONLY_NODE_TYPES = frozenset({"Note", "MarkdownNote", "PrimitiveNode", "GetNode", "SetNode", "Reroute"})

# seed 系 INT widget の直後に widgets_values へ続く control_after_generate マーカー
_CONTROL_AFTER_GENERATE_VALUES = frozenset({"fixed", "increment", "decrement", "randomize"})

_MISSING = object()


class WorkflowConversionError(Exception):
    """UI形式ワークフローを API 形式に変換できない場合に送出される。"""


def is_api_format(workflow: Any) -> bool:
    """すでに API 形式（{node_id: {class_type, inputs}}）なら True。"""
    if not isinstance(workflow, dict):
        return False
    if "nodes" in workflow and "links" in workflow:
        return False
    for key, value in workflow.items():
        if key in ("prompt", "extra_data", "client_id"):
            continue
        if isinstance(value, dict) and "class_type" in value:
            return True
    return False


def convert_ui_to_api(workflow: dict, object_info: dict) -> dict:
    """UI形式ワークフローを API 形式に変換する。

    Args:
        workflow: UI 形式（nodes / links キーを持つ dict）
        object_info: GET /object_info の応答（{node_type: schema}）

    Returns:
        API 形式 dict: {node_id_str: {class_type, inputs, _meta}}
    """
    if is_api_format(workflow):
        return workflow
    if not isinstance(workflow, dict):
        raise WorkflowConversionError("Workflow must be a JSON object")
    if not isinstance(workflow.get("nodes"), list) or not isinstance(workflow.get("links"), list):
        raise WorkflowConversionError("Workflow is missing 'nodes' or 'links' list")
    if not isinstance(object_info, dict):
        raise WorkflowConversionError("object_info must be a JSON object")

    workflow = copy.deepcopy(workflow)
    nodes = [n for n in workflow["nodes"] if isinstance(n, dict)]
    links = list(workflow["links"])

    link_map = _build_link_map(links)
    primitive_values = _collect_primitive_values(nodes)

    api_prompt: dict[str, dict] = {}
    for node in nodes:
        node_id = str(node.get("id"))
        node_type = node.get("type")
        if not node_type:
            continue
        if node.get("mode") in (_MODE_MUTED, _MODE_BYPASS) or node_type in _UI_ONLY_NODE_TYPES:
            continue
        try:
            api_prompt[node_id] = _build_api_node(node, node_type, object_info, link_map, primitive_values)
        except Exception:
            # 個別ノードの変換失敗で全体を落とさない（comfy-cli と同じ方針）
            continue
    _strip_orphan_link_inputs(api_prompt)
    return api_prompt


def _build_link_map(links: list) -> dict[int, dict]:
    """links の6要素タプル [link_id, src_id, src_slot, tgt_id, tgt_slot, type] を dict 化する。"""
    link_map: dict[int, dict] = {}
    for link in links:
        if not isinstance(link, (list, tuple)) or len(link) < 6:
            continue
        link_id, src_id, src_slot, tgt_id, tgt_slot, _link_type = link[:6]
        link_map[link_id] = {
            "source_id": src_id,
            "source_slot": src_slot,
            "target_id": tgt_id,
            "target_slot": tgt_slot,
            "type": _link_type,
        }
    return link_map


def _collect_primitive_values(nodes: list[dict]) -> dict[str, Any]:
    """PrimitiveNode の値を {node_id: value} で収集する（リンク解決時にインライン展開）。"""
    out: dict[str, Any] = {}
    for node in nodes:
        if node.get("type") != "PrimitiveNode":
            continue
        widgets = node.get("widgets_values")
        if isinstance(widgets, list) and widgets:
            out[str(node.get("id"))] = widgets[0]
    return out


def _schema_for(node_type: str, node: dict, object_info: dict) -> dict | None:
    properties = node.get("properties") or {}
    alt_name = properties.get("Node name for S&R")
    if isinstance(alt_name, str) and alt_name in object_info:
        return object_info[alt_name]
    return object_info.get(node_type) if isinstance(node_type, str) else None


def _schema_input_def(schema: Any) -> dict:
    if not isinstance(schema, dict):
        return {}
    input_def = schema.get("input")
    return input_def if isinstance(input_def, dict) else {}


def _is_widget_input(input_spec: Any) -> bool:
    """入力 spec が widget 型（widgets_values に値を持つ）かどうか。

    ponytail: COMFY_*COMBO* のサブ入力展開は非対応（スロット1つとして消費する）。
    """
    if not isinstance(input_spec, (list, tuple)) or not input_spec:
        return False
    options = input_spec[1] if len(input_spec) >= 2 and isinstance(input_spec[1], dict) else {}
    if options.get("forceInput") or options.get("defaultInput"):
        return False
    input_type = input_spec[0]
    if isinstance(input_type, (list, tuple)):
        return True  # COMBO（選択肢リスト）
    if isinstance(input_type, str):
        if input_type in ("", "*"):
            return False  # ワイルドカード接続型は widget 無し
        if input_type in {"INT", "FLOAT", "STRING", "BOOLEAN", "COMBO"}:
            return True
        if not input_type.isupper():
            return True  # カスタム widget 型（lowercase）
    return False


def _has_control_after_generate_companion(input_name: str, input_spec: Any, next_value: Any) -> bool:
    """seed 系 INT widget の直後に control_after_generate マーカーが続くか。"""
    if not isinstance(next_value, str) or next_value not in _CONTROL_AFTER_GENERATE_VALUES:
        return False
    options = input_spec[1] if len(input_spec) >= 2 and isinstance(input_spec[1], dict) else {}
    if options.get("control_after_generate"):
        return True
    input_type = input_spec[0] if input_spec else None
    leaf = input_name.rsplit(".", 1)[-1]
    return input_type == "INT" and leaf in ("seed", "noise_seed")


def _schema_widget_pairs(schema: dict, widget_values: list) -> list[tuple[str, Any]]:
    """スキーマの widget 入力と widgets_values スロットを順に対応付ける。

    required→optional の順で、widget 入力ごとにスロットを1つ消費する。
    control_after_generate マーカー文字列は消費して捨てる。
    """
    input_def = _schema_input_def(schema)
    pairs: list[tuple[str, Any]] = []
    vidx = 0

    def consume(name: str, spec: Any) -> None:
        nonlocal vidx
        if not _is_widget_input(spec) or vidx >= len(widget_values):
            return
        pairs.append((name, widget_values[vidx]))
        vidx += 1
        if vidx < len(widget_values) and _has_control_after_generate_companion(name, spec, widget_values[vidx]):
            vidx += 1

    for section in ("required", "optional"):
        section_def = input_def.get(section) or {}
        if not isinstance(section_def, dict):
            continue
        for input_name, input_spec in section_def.items():
            consume(input_name, input_spec)
    return pairs


def _collect_widget_inputs(
    node: dict, node_type: str, object_info: dict, link_inputs: dict[str, list]
) -> dict[str, Any]:
    """widgets_values を入力名と対応付ける。リンク接続済みの入力は値を使わない。"""
    widget_values = node.get("widgets_values")
    if widget_values is None:
        return {}
    out: dict[str, Any] = {}
    if isinstance(widget_values, dict):
        # V3 新 UI の自己記述形式
        for key, value in widget_values.items():
            if key in ("videopreview", "preview") or key in link_inputs:
                continue
            out[key] = _wrap_widget_value(value)
        return out
    if not isinstance(widget_values, list):
        return {}

    schema = _schema_for(node_type, node, object_info)
    if schema:
        for name, value in _schema_widget_pairs(schema, widget_values):
            if not name or name in link_inputs:
                continue
            out[name] = _wrap_widget_value(value)
        return out
    # ponytail: スキーマ無しノードは widget を無視（ComfyUI に未ロードのノード型は
    # 実行できないため、静かに落ちるより送信前に気付ける）
    return out


def _extract_default(input_spec: Any) -> Any:
    if not isinstance(input_spec, (list, tuple)) or not input_spec:
        return _MISSING
    input_type = input_spec[0]
    options = input_spec[1] if len(input_spec) >= 2 and isinstance(input_spec[1], dict) else {}
    if "default" in options:
        return options["default"]
    if isinstance(input_type, list) and input_type:
        return input_type[0]  # COMBO は先頭要素
    return _MISSING


def _collect_default_inputs(schema: dict | None, widget_inputs: dict, link_inputs: dict) -> dict:
    """widget / link で埋まっていない入力へ /object_info のデフォルトを補完する。"""
    if not schema:
        return {}
    input_def = _schema_input_def(schema)
    defaults: dict[str, Any] = {}
    for section in ("required", "optional"):
        section_def = input_def.get(section) or {}
        if not isinstance(section_def, dict):
            continue
        for input_name, input_spec in section_def.items():
            if input_name in widget_inputs or input_name in link_inputs:
                continue
            default = _extract_default(input_spec)
            if default is not _MISSING:
                defaults[input_name] = _wrap_widget_value(default)
    return defaults


def _wrap_widget_value(value: Any) -> Any:
    """リスト型 widget 値を [node_id, slot] リンクと区別できるようラップする。"""
    return {"__value__": value} if isinstance(value, list) else value


def _normalize_combo_values(schema: dict | None, inputs: dict[str, Any]) -> None:
    """COMBO 値をスキーマの選択肢と大文字小文字だけ違う場合に正規化する。"""
    if not schema:
        return
    input_def = _schema_input_def(schema)
    for section in ("required", "optional"):
        section_def = input_def.get(section) or {}
        if not isinstance(section_def, dict):
            continue
        for input_name, input_spec in section_def.items():
            if input_name not in inputs:
                continue
            value = inputs[input_name]
            if not isinstance(value, str) or not isinstance(input_spec, (list, tuple)) or not input_spec:
                continue
            allowed = input_spec[0]
            if not isinstance(allowed, (list, tuple)) or value in allowed:
                continue
            lower = value.lower()
            for option in allowed:
                if isinstance(option, str) and option.lower() == lower:
                    inputs[input_name] = option
                    break


def _build_api_node(
    node: dict, node_type: str, object_info: dict, link_map: dict[int, dict], primitive_values: dict[str, Any]
) -> dict:
    api_node: dict = {"inputs": {}, "class_type": node_type}
    schema = _schema_for(node_type, node, object_info) or {}

    # NOUS: タグ注入は _meta.title を読む。UI ノードの title をここへ写す。
    if "title" in node:
        api_node["_meta"] = {"title": node["title"]}
    else:
        api_node["_meta"] = {"title": schema.get("display_name") or node_type}

    link_inputs: dict[str, list] = {}
    for inp in node.get("inputs") or []:
        if not isinstance(inp, dict):
            continue
        input_name = inp.get("name")
        link_id = inp.get("link")
        if not input_name or not isinstance(link_id, int) or link_id not in link_map:
            continue
        ld = link_map[link_id]
        src_id = str(ld["source_id"])
        if src_id in primitive_values:
            # PrimitiveNode 由来の値はインライン化（PrimitiveNode 自体は出力されない）
            link_inputs[input_name] = _wrap_widget_value(primitive_values[src_id])
        else:
            link_inputs[input_name] = [src_id, ld["source_slot"]]

    widget_inputs = _collect_widget_inputs(node, node_type, object_info, link_inputs)
    default_inputs = _collect_default_inputs(schema, widget_inputs, link_inputs)

    # widget → デフォルト → リンク の順で出力（comfy-cli と同じ並び）
    for source in (widget_inputs, default_inputs, link_inputs):
        for key, value in source.items():
            if key not in api_node["inputs"]:
                api_node["inputs"][key] = value

    _normalize_combo_values(schema, api_node["inputs"])
    return api_node


def _strip_orphan_link_inputs(api_prompt: dict[str, dict]) -> None:
    """存在しないノードを参照するリンク入力を削除する。"""
    for node in api_prompt.values():
        inputs = node.get("inputs")
        if not isinstance(inputs, dict):
            continue
        for name in list(inputs):
            value = inputs[name]
            if isinstance(value, list) and len(value) == 2 and isinstance(value[0], str) and value[0] not in api_prompt:
                del inputs[name]
```

- [ ] **Step 5: テストを実行して合格を確認**

Run: `python -m pytest tests/unit/test_workflow_converter.py -v`
Expected: 13 tests PASS

- [ ] **Step 6: コミット**

```bash
git add nous/infrastructure/image_gen/workflow_converter.py tests/unit/workflow_fixtures.py tests/unit/test_workflow_converter.py
git commit -m "feat: add ComfyUI UI-to-API workflow converter"
```

- [ ] **Step 6: 実行時パラメータ適用関数 `apply_generation_params` を追加（失敗テスト → 実装 → 合格）**

Task 2 以降で使用する。変換後・読込後のワークフローにサイズ・枚数・ランダムシードを適用する。テストは `tests/unit/test_workflow_converter.py` 末尾に追加:

```python
def test_apply_generation_params_injects_size_batch_and_seed():
    from nous.infrastructure.image_gen.workflow_converter import apply_generation_params

    workflow = {
        "5": {"class_type": "EmptyLatentImage", "inputs": {"width": 512, "height": 512, "batch_size": 1}},
        "9": {"class_type": "KSampler", "inputs": {"seed": 123, "noise_seed": 123, "steps": 30}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": ""}},
    }
    out = apply_generation_params(workflow, width=896, height=1152, n=3, seed=42)

    assert out["5"]["inputs"]["width"] == 896
    assert out["5"]["inputs"]["height"] == 1152
    assert out["5"]["inputs"]["batch_size"] == 3
    assert out["9"]["inputs"]["seed"] == 42
    assert out["9"]["inputs"]["noise_seed"] == 42
    assert out["6"]["inputs"]["text"] == ""  # 無関係ノードは無変更


def test_apply_generation_params_skips_linked_inputs():
    from nous.infrastructure.image_gen.workflow_converter import apply_generation_params

    # リンク入力（[node_id, slot] リスト）は上書きしない / batch_size は最低1
    workflow = {
        "5": {"class_type": "EmptyLatentImage", "inputs": {"width": ["6", 0], "height": 512, "batch_size": 0}},
    }
    out = apply_generation_params(workflow, width=1024, height=1536, n=0, seed=7)

    assert out["5"]["inputs"]["width"] == ["6", 0]  # リンクは維持
    assert out["5"]["inputs"]["height"] == 1536
    assert out["5"]["inputs"]["batch_size"] == 1


def test_apply_generation_params_seed_none_randomizes():
    from nous.infrastructure.image_gen.workflow_converter import apply_generation_params

    workflow = {"9": {"class_type": "KSampler", "inputs": {"seed": 1, "noise_seed": 1}}}
    out = apply_generation_params(workflow, width=512, height=512, n=1, seed=None)

    assert out["9"]["inputs"]["seed"] != 1  # ランダム化（1 と一致する確率は実質 0）
    assert out["9"]["inputs"]["seed"] == out["9"]["inputs"]["noise_seed"]
    assert 1 <= out["9"]["inputs"]["seed"] < 2**63
```

Run: `python -m pytest tests/unit/test_workflow_converter.py -v`
Expected: FAIL — `ImportError: cannot import name 'apply_generation_params'`

実装（`nous/infrastructure/image_gen/workflow_converter.py` 末尾に追加）:

```python
def apply_generation_params(workflow: dict, *, width: int, height: int, n: int, seed: int | None = None) -> dict:
    """保存済みワークフローへ実行時パラメータを適用する（毎回の生成時に呼ぶ）。

    - class_type == "EmptyLatentImage" のノード: width / height / batch_size を注入
      （リンク入力（[node_id, slot] リスト）は上書きしない。batch_size は最低 1）
    - 入力名が seed / noise_seed の INT 入力: シードを上書き（ワークフロー保存時の
      固定 seed 対策。seed=None なら毎回ランダム）

    対象ノードが無ければ無変更で同じ dict を返す。
    """
    if seed is None:
        seed = random.randint(1, 2**63 - 1)
    for node in workflow.values():
        if not isinstance(node, dict):
            continue
        inputs = node.get("inputs")
        if not isinstance(inputs, dict):
            continue
        if node.get("class_type") == "EmptyLatentImage":
            if "width" in inputs and isinstance(inputs["width"], (int, float)):
                inputs["width"] = int(width)
            if "height" in inputs and isinstance(inputs["height"], (int, float)):
                inputs["height"] = int(height)
            if "batch_size" in inputs and isinstance(inputs["batch_size"], (int, float)):
                inputs["batch_size"] = max(1, int(n))
        for name in ("seed", "noise_seed"):
            if name in inputs and isinstance(inputs[name], (int, float)):
                inputs[name] = seed
    return workflow
```

Run: `python -m pytest tests/unit/test_workflow_converter.py -v`
Expected: 全 PASS

- [ ] **Step 7: コミット**

```bash
git add nous/infrastructure/image_gen/workflow_converter.py tests/unit/test_workflow_converter.py
git commit -m "feat: apply generation params (size, batch, random seed) to workflows at runtime"
```

---

### Task 2: ComfyUIProvider に /userdata ワークフロー取得と変換統合

**Files:**
- Modify: `nous/infrastructure/image_gen/comfyui.py`
- Modify: `tests/unit/test_comfyui_provider.py`

**Interfaces:**
- Consumes (Task 1): `is_api_format`, `convert_ui_to_api`, `WorkflowConversionError`
- Produces（Task 3 が使用）:
  - `ComfyUIProvider.__init__` の新シグネチャ: `api_url="http://localhost:8188", width=1024, height=1024, workflow_template="", workflow_source="local", workflow_name="", object_info_cache_ttl=300.0, timeout_seconds=180.0` — **checkpoint / loras / steps / cfg / sampler / scheduler / seed / denoise 引数は削除（ワークフロー側に一元化）**
  - `ComfyUIProvider._load_workflow(*, prompt: str, negative_prompt: str, image_filename: str | None, seed: int) -> dict` — API形式ワークフローを返す（local: 従来のファイル読込＋レガシー置換、comfyui: /userdata 取得→変換）
  - `ComfyUIProvider._fetch_userdata_workflow() -> dict` — GET `/userdata/workflows/{name}.json` で UI 形式 dict を取得。404 は FileNotFoundError、不正 JSON は WorkflowConversionError
  - `ComfyUIProvider._get_object_info() -> dict` — GET `/object_info` を TTL キャッシュ付きで取得
  - `generate()` は `_load_workflow` の直後に `apply_generation_params(workflow, width=self._width, height=self._height, n=n, seed=seed)` を適用し、その後に NOUS: タグ注入

- [ ] **Step 1: 既存テストの修正＋失敗テストを追加（tests/unit/test_comfyui_provider.py）**

既存テストのうち、廃止対象の注入機能を検証していたテストを修正する（新 __init__ シグネチャでは AttributeError になるため）:

**削除するテスト（LoRA 注入系・パラメータタグ注入系）:**
- `test_nous_lora_single_uses_tagged_node` / `test_nous_lora_chain_creates_nodes_and_remaps` / `test_nous_lora_empty_config_leaves_node_untouched` / `test_nous_lora_power_loader_slots` / `test_nous_lora_power_loader_empty_config_disables_all_slots` / `test_nous_lora_unsupported_class_type_skipped`
- `test_nous_injects_simple_keys`（11種タグ検証 → 下記 `test_nous_injects_remaining_keys` に書き換え）
- `test_nous_int_constant_injects_value_field` / `test_nous_float_constant_injects_value_field` / `test_nous_constant_branch_keeps_non_constant_behavior`（→ 下記書き換え版に置換）

**書き換えるテスト（廃止パラメータの参照を除去）:**
- `test_generate_template_mode_injects_nous_tags`: checkpoint / lora タグ注入の検証部分を除去
- `test_generate_template_mode_legacy_placeholders`: `{{seed}}` 置換は維持（置換値はランダムになるため、注入値が int であることの検証に変更）
- `test_builtin_image_generate_skips_non_display_images`: Provider 構築パラメータ（checkpoint 等）の参照を除去

以下を追加する（既存テスト修正後の新規分）:

```python
# ============================================================
# 実行時パラメータ適用（apply_generation_params 統合）
# ============================================================

@pytest.mark.asyncio
async def test_generate_injects_size_batch_and_random_seed():
    """workflow_source='comfyui': 変換後にサイズ・枚数・ランダムシードが適用される。"""
    import json as _json

    from tests.unit.workflow_fixtures import MINI_UI_WORKFLOW, OBJECT_INFO

    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = MagicMock()

        userdata_resp = MagicMock()
        userdata_resp.status_code = 200
        userdata_resp.text = _json.dumps(MINI_UI_WORKFLOW)

        object_info_resp = MagicMock()
        object_info_resp.status_code = 200
        object_info_resp.json.return_value = OBJECT_INFO

        post_resp = MagicMock()
        post_resp.status_code = 200
        post_resp.json.return_value = {"prompt_id": "pid-1"}

        hist_resp = MagicMock()
        hist_resp.json.return_value = {
            "pid-1": {"outputs": {"13": {"images": [{"filename": "a.png", "type": "output"}, {"filename": "b.png", "type": "output"}]}}}
        }

        img_resp = MagicMock()
        img_resp.status_code = 200
        img_resp.content = b"pngdata"

        mock_client.get = AsyncMock(side_effect=[userdata_resp, object_info_resp, hist_resp, img_resp, img_resp])
        mock_client.post = AsyncMock(return_value=post_resp)
        mock_client_class.return_value = mock_client

        from nous.infrastructure.image_gen.comfyui import ComfyUIProvider

        provider = ComfyUIProvider(
            api_url="http://localhost:8188",
            workflow_source="comfyui",
            workflow_name="Anima_T2I_Turbo_Aesthetic.json",
            width=896,
            height=1152,
        )
        with patch("asyncio.sleep", new=AsyncMock(return_value=None)):
            images = await provider.generate(prompt="The Herta, dancing", size="896x1152", n=2)

        assert len(images) == 2
        post_call = mock_client.post.call_args
        sent = post_call[1]["json"]["prompt"]
        # 固定 seed 875817230929465 がランダム化されている（MINI_UI_WORKFLOW の KSampler は固定 seed）
        assert sent["9"]["inputs"]["seed"] != 875817230929465
        assert sent["9"]["inputs"]["seed"] == sent["9"]["inputs"]["noise_seed"]
        assert 1 <= sent["9"]["inputs"]["seed"] < 2**63
        # NOUS:prompt タグ注入は従来どおり
        assert sent["6"]["inputs"]["text"] == "The Herta, dancing"


@pytest.mark.asyncio
async def test_nous_injects_remaining_keys():
    """残存タグ（prompt / negative_prompt / reference_image / width / height / seed）だけが注入される。"""
    from nous.infrastructure.image_gen.comfyui import ComfyUIProvider

    provider = ComfyUIProvider(api_url="http://localhost:8188", workflow_template="dummy.json")
    workflow = {
        "1": {"class_type": "CLIPTextEncode", "inputs": {"text": ""}, "_meta": {"title": "NOUS:prompt"}},
        "2": {"class_type": "CLIPTextEncode", "inputs": {"text": ""}, "_meta": {"title": "NOUS:negative_prompt"}},
        "3": {"class_type": "LoadImage", "inputs": {"image": ""}, "_meta": {"title": "NOUS:reference_image"}},
        "4": {"class_type": "INTConstant", "inputs": {"value": 0}, "_meta": {"title": "NOUS:width"}},
        "5": {"class_type": "INTConstant", "inputs": {"value": 0}, "_meta": {"title": "NOUS:height"}},
        "6": {"class_type": "INTConstant", "inputs": {"value": -370}, "_meta": {"title": "NOUS:seed"}},
        "7": {"class_type": "LoraLoader", "inputs": {}, "_meta": {"title": "NOUS:lora"}},
        "8": {"class_type": "CheckpointLoaderSimple", "inputs": {}, "_meta": {"title": "NOUS:checkpoint"}},
    }
    out = provider._apply_nous_injections(
        workflow,
        prompt="p1",
        negative_prompt="n1",
        image_filename="ref.png",
        seed=12345,
    )
    assert out["1"]["inputs"]["text"] == "p1"
    assert out["2"]["inputs"]["text"] == "n1"
    assert out["3"]["inputs"]["image"] == "ref.png"
    assert out["4"]["inputs"]["value"] == 1024  # 既定 width
    assert out["5"]["inputs"]["value"] == 1024  # 既定 height
    assert out["6"]["inputs"]["value"] == 12345  # seed は generate 側で計算された値
    # 廃止タグは無視される（未知タグとして warning ログのみ）
    assert "lora_name" not in out["7"]["inputs"]
    assert "ckpt_name" not in out["8"]["inputs"]


@pytest.mark.asyncio
async def test_workflow_source_comfyui_requires_name():
    with pytest.raises(ValueError, match="workflow_name"):
        ComfyUIProvider(api_url="http://localhost:8188", workflow_source="comfyui")


@pytest.mark.asyncio
async def test_fetch_userdata_workflow_404():
    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = MagicMock()
        resp = MagicMock()
        resp.status_code = 404
        mock_client.get = AsyncMock(return_value=resp)
        mock_client_class.return_value = mock_client

        from nous.infrastructure.image_gen.comfyui import ComfyUIProvider

        provider = ComfyUIProvider(api_url="http://localhost:8188", workflow_source="comfyui", workflow_name="missing.json")
        with pytest.raises(FileNotFoundError, match="Workflow not found"):
            await provider._fetch_userdata_workflow()


@pytest.mark.asyncio
async def test_object_info_is_cached():
    """object_info は TTL 内なら再取得しない。"""
    from tests.unit.workflow_fixtures import OBJECT_INFO

    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = MagicMock()
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = OBJECT_INFO
        mock_client.get = AsyncMock(return_value=resp)
        mock_client_class.return_value = mock_client

        from nous.infrastructure.image_gen.comfyui import ComfyUIProvider

        provider = ComfyUIProvider(api_url="http://localhost:8188", workflow_source="comfyui", workflow_name="a.json")
        await provider._get_object_info()
        await provider._get_object_info()
        object_info_calls = [c for c in mock_client.get.call_args_list if c.args[0].endswith("/object_info")]
        assert len(object_info_calls) == 1


@pytest.mark.asyncio
async def test_workflow_source_local_rejects_empty_template():
    """従来の local ソースは workflow_template 必須のまま（後方互換）。"""
    with pytest.raises(ValueError, match="workflow_template"):
        ComfyUIProvider(api_url="http://localhost:8188", workflow_template="")
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `python -m pytest tests/unit/test_comfyui_provider.py -v`
Expected: FAIL — 新規テストが AttributeError / ImportError で失敗（既存テストは Step 1 で修正済みのため PASS のまま）

- [ ] **Step 3: comfyui.py を修正**

`__init__` のシグネチャと冒頭バリデーションを変更:

```python
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
```

`generate()` のテンプレート読込部分を置き換え（`import json as _json` / `from pathlib import Path as _Path` の import と、`{{...}}` 置換・`_json.loads` までを含むブロックを差し替え。seed 計算は `_load_workflow` 呼び出しより前に移動）:

```python
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
```

モジュール冒頭の import に追加:

```python
from .workflow_converter import WorkflowConversionError, apply_generation_params, convert_ui_to_api, is_api_format
```

（`generate()` 内にあった `import json as _json` / `from pathlib import Path as _Path` は削除済みのため、`_load_workflow` 内で再宣言している。）

**`_apply_nous_injections` と `_inject_nous_key` を書き換え、LoRA 注入メソッド一式を削除する:**

`_apply_nous_injections` から LoRA 処理を除去:

```python
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
```

`_inject_nous_key` を書き換え（INTConstant 分岐は width / height / seed のみ。seed は引数の値＝毎回ランダム）:

```python
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
```

**削除するメソッド（LoRA 注入一式）:**
- `_inject_lora` / `_inject_lora_chain` / `_inject_power_lora` / `_remap_lora_ref` / `_normalize_lora_path`
- 既存 `_inject_nous_key` 内の INTConstant 以外の seed / width / height / steps / cfg / sampler / scheduler / denoise / checkpoint 分岐（`inputs["seed"] = seed` 等のフィールド注入）は上記書き換え版で全て除去済み

- [ ] **Step 4: テストを実行して合格を確認**

Run: `python -m pytest tests/unit/test_comfyui_provider.py -v`
Expected: 修正済み既存テスト（LoRA/パラメータ注入系 6 件削除・4 件書き換え）＋新規 6 件が全 PASS

- [ ] **Step 5: コミット**

```bash
git add nous/infrastructure/image_gen/comfyui.py tests/unit/test_comfyui_provider.py
git commit -m "feat: run ComfyUI saved workflows via /userdata with UI-to-API conversion"
```

---

### Task 3: 設定の配線（ToolConfig + builtin.py + routers）

**Files:**
- Modify: `nous/domain/tool_config.py`（新フィールド追加＋廃止フィールド8個を削除）
- Modify: `nous/application/chat/tools/builtin.py:290-306`（Provider 構築のパラメータ削減）
- Modify: `nous/api/http/routers/image_gen.py`（test ルートの Provider 構築のパラメータ削減）
- Modify: `nous/api/http/sections/chat/chat_sidebar_media.py`（ワークフロー設定フォーム3つ組化＋廃止フィールドのフォーム削除）
- Modify: `nous/api/http/static/chat/chat-settings.js`（設定のロード/保存に新フィールド追加＋廃止フィールドの行削除）
- Modify: `tests/unit/test_comfyui_provider.py`（ToolConfig デフォルトのテスト追記）

**Interfaces:**
- Consumes (Task 2): `ComfyUIProvider(api_url=..., width=..., height=..., workflow_template=..., workflow_source=..., workflow_name=...)` — **checkpoint / loras / steps / cfg / sampler / scheduler / denoise / seed 引数は渡さない**
- Produces: persona 別 config.json のフィールド構成
  - 追加: `image_gen_comfyui_workflow_source`（`"local"` 既定 | `"comfyui"`）、`image_gen_comfyui_workflow_name`（例 `"Anima_T2I_Turbo_Aesthetic.json"`）
  - 削除: `image_gen_comfyui_checkpoint` / `_loras` / `_steps` / `_cfg` / `_sampler` / `_scheduler` / `_denoise` / `_seed`
  - 維持: `image_gen_comfyui_width` / `_height` / `image_gen_presets` / `image_gen_default_preset` / `image_gen_max_width` / `_max_height`（サイズ指定機構は残す＝ユーザー決定）

- [ ] **Step 1: 失敗テストを追加（test_comfyui_provider.py の ToolConfig セクションへ）**

```python
def test_tool_config_workflow_source_defaults():
    """新フィールドのデフォルトは local + 空名（後方互換）。"""
    from nous.domain.tool_config import ToolConfig

    config = ToolConfig()
    assert config.image_gen_comfyui_workflow_source == "local"
    assert config.image_gen_comfyui_workflow_name == ""


def test_tool_config_removed_params_absent():
    """廃止フィールド（checkpoint/loras/steps/cfg/sampler/scheduler/denoise/seed）が無いこと。"""
    from nous.domain.tool_config import ToolConfig

    config = ToolConfig()
    for field in (
        "image_gen_comfyui_checkpoint",
        "image_gen_comfyui_loras",
        "image_gen_comfyui_steps",
        "image_gen_comfyui_cfg",
        "image_gen_comfyui_sampler",
        "image_gen_comfyui_scheduler",
        "image_gen_comfyui_denoise",
        "image_gen_comfyui_seed",
    ):
        assert not hasattr(config, field), f"{field} は廃止されているべき"
    # サイズ系は維持
    assert config.image_gen_comfyui_width == 1024
    assert config.image_gen_comfyui_height == 1024
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `python -m pytest tests/unit/test_comfyui_provider.py::test_tool_config_workflow_source_defaults tests/unit/test_comfyui_provider.py::test_tool_config_removed_params_absent -v`
Expected: FAIL — `AttributeError: image_gen_comfyui_workflow_source` / `hasattr` が True

- [ ] **Step 3: 実装**

`nous/domain/tool_config.py` — `image_gen_comfyui_workflow_template` の直後に追加:

```python
    image_gen_comfyui_workflow_template: str = "workflows/default_node.json"  # path to API-format JSON workflow template (required only for workflow_source="local")
    image_gen_comfyui_workflow_source: str = "local"  # "local" | "comfyui"（ComfyUI 側 user/default/workflows から取得）
    image_gen_comfyui_workflow_name: str = ""  # workflow_source="comfyui" 時の ComfyUI 側ワークフローファイル名
```

あわせて**廃止フィールド8個を削除**（モデル/LoRA/サンプリングパラメータはワークフロー側に一元化）:

```python
    # ↓ 削除（パラメータはワークフロー側に一元化）
    # image_gen_comfyui_checkpoint: str = ""
    # image_gen_comfyui_loras: str = "[]"
    # image_gen_comfyui_steps: int = 28
    # image_gen_comfyui_cfg: float = 5.5
    # image_gen_comfyui_sampler: str = "euler_ancestral"
    # image_gen_comfyui_scheduler: str = "normal"
    # image_gen_comfyui_seed: int = 0  # 0=ランダム
    # image_gen_comfyui_denoise: float = 0.7
```

（サイズ系 `image_gen_comfyui_width` / `_height` / `image_gen_presets` / `image_gen_default_preset` / `image_gen_max_width` / `_max_height` は**残す**。persona の config.json に残っている廃止フィールドは pydantic が無視するため削除不要・無害。）

`nous/application/chat/tools/builtin.py` — `_handle_image_generate` 内の `ComfyUIProvider(...)` 呼び出し（L290-306）を書き換え。checkpoint / loras / steps / cfg / sampler / scheduler / seed / denoise の引数と LoRA パース（`loras_raw` / `json.loads`）を削除し、workflow_source / workflow_name を追加:

```python
        comfyui_url = getattr(config, "image_gen_comfyui_url", "") or "http://localhost:8188"

        provider = ComfyUIProvider(
            api_url=comfyui_url,
            width=w,
            height=h,
            workflow_template=getattr(config, "image_gen_comfyui_workflow_template", ""),
            workflow_source=getattr(config, "image_gen_comfyui_workflow_source", "local"),
            workflow_name=getattr(config, "image_gen_comfyui_workflow_name", ""),
            timeout_seconds=getattr(config, "image_gen_comfyui_timeout_seconds", 180),
        )
```

（※`w` / `h` は既存の preset 解決＋max クランプ（L226-253）の結果をそのまま使う。seed 引数は削除済みのため、従来 `seed=getattr(config, "image_gen_comfyui_seed", 0)` を渡していた行は除去。）

`nous/api/http/routers/image_gen.py` — `test_image_gen` の `ComfyUIProvider(...)` 呼び出しも同様に書き換え:

```python
        provider = ComfyUIProvider(
            api_url=comfyui_url,
            width=body.get("width", getattr(config, "image_gen_comfyui_width", 1024)),
            height=body.get("height", getattr(config, "image_gen_comfyui_height", 1024)),
            workflow_template=getattr(config, "image_gen_comfyui_workflow_template", ""),
            workflow_source=getattr(config, "image_gen_comfyui_workflow_source", "local"),
            workflow_name=getattr(config, "image_gen_comfyui_workflow_name", ""),
            timeout_seconds=getattr(config, "image_gen_comfyui_timeout_seconds", 180),
        )
```

（※test ルートの `steps` / `cfg` / `sampler` / `scheduler` / `denoise` / `seed` / `loras` の body/config 参照は全て除去。LoRA リストの body 優先ロジック（`if "loras" in body ...`）も削除。）

- [ ] **Step 4: テストを実行して合格を確認**

Run: `python -m pytest tests/unit/test_comfyui_provider.py tests/unit/test_builtin_handlers.py -v`
Expected: 全 PASS（builtin の既存テストは getattr デフォルトで影響なし）

- [ ] **Step 5: WebUI設定画面に対応（フォーム削減 + 3つ組追加 + ロード/保存 JS）**

バックエンドの保存API（`chat_management.py:_do_save_chat_config`）は `ChatConfig._all_flat_fields()` と body を動的マージする方式なので、ToolConfig のフィールド追加・削除は保存/ロードに自動反映される。変更はフロントエンド2ファイルのみ。

**まず廃止フィールドのフォームを削除する**（`nous/api/http/sections/chat/chat_sidebar_media.py` の `_render_image_section()`）:

| 削除するフォーム | 行 |
|---|---|
| チェックポイント（checkpoint） | L55 |
| LoRA 動的リスト（lora-list / lora-add） | L69-71 |
| steps range | L131 |
| cfg range | L138 |
| sampler select | L145 |
| scheduler select | L171 |
| denoise range | L188 |
| seed number | L192 |

（維持: enabled トグル L38 / comfyui-url L50 / self-portrait L60 / negative L64 / width・height L77-79 / max 系 L86-88 / presets 9種 L99-109 / default-preset L113-123 / 参照画像アップロード L204-215 / テストボタン L217。サンプラー・スケジューラ等の select 削除に伴い、`chat-settings.js` の `applyChatConfig()` L281-282 の sampler/scheduler 復元行と `saveChatConfig()` の該当 payload 行も削除する。checkpoint / loras / seed / denoise のフォーム復元・payload 行も同様に削除。フォームに無いフィールドは payload に含めないこと（動的マージは body に無いフィールドを現行値のままにするため、既存 config.json に残っていても無害）。）

次に既存のワークフローテンプレート入力（L196-202）を、取得元セレクト + ワークフロー名入力 + 既存テンプレート入力の3つ組に置き換える:

```html
                                    <!-- workflow source selector -->
                                    <div style="margin-top:8px;">
                                        <div class="chat-field-label" style="font-size:0.78rem;">ワークフロー取得元</div>
                                        <select id="chat-image-gen-workflow-source" class="chat-field-input" style="width:100%;">
                                            <option value="local" selected>Nous サーバー（data/workflows/）</option>
                                            <option value="comfyui">ComfyUI サーバー（user/default/workflows/）</option>
                                        </select>
                                    </div>
                                    <!-- workflow name (comfyui source) -->
                                    <div style="margin-top:8px;">
                                        <div class="chat-field-label" style="font-size:0.78rem;">ワークフロー名（ComfyUI 側のファイル名）</div>
                                        <input type="text" id="chat-image-gen-workflow-name" class="chat-field-input"
                                            placeholder="例: Anima_T2I_Turbo_Aesthetic.json"
                                            style="width:100%;font-size:0.78rem;" />
                                    </div>
                                    <!-- workflow template path -->
                                    <div style="margin-top:8px;">
                                        <div class="chat-field-label" style="font-size:0.78rem;">ワークフローテンプレート（必須・Nous サーバー側のパス）</div>
                                        <input type="text" id="chat-image-gen-template" class="chat-field-input"
                                            placeholder="例: /data/workflows/pony_ipadapter.json"
                                            style="width:100%;font-size:0.78rem;" />
                                    </div>
```

`nous/api/http/static/chat/chat-settings.js` — `applyChatConfig()` の既存テンプレート復元（L286-288）の直後に追加:

```js
  set("chat-image-gen-workflow-source", cfg.image_gen_comfyui_workflow_source);
  var workflowNameInput = document.getElementById("chat-image-gen-workflow-name");
  if (workflowNameInput) workflowNameInput.value = cfg.image_gen_comfyui_workflow_name || "";
```

`nous/api/http/static/chat/chat-settings.js` — `saveChatConfig()` の既存テンプレート収集（L524）の直後に追加:

```js
    image_gen_comfyui_workflow_source: document.getElementById("chat-image-gen-workflow-source")?.value || "local",
    image_gen_comfyui_workflow_name: document.getElementById("chat-image-gen-workflow-name")?.value || "",
```

※ `set()` は sampler/scheduler の select 復元にも使われている汎用ヘルパー（L281-282）で、select の value 代入にそのまま使える。フロントエンドの自動テストは既存テストに存在しないため、検証は手動（WebUI 設定画面で保存 → `GET /api/chat/{persona}/config` で値が返る・config.json に保存されることを確認）。この手動確認は Task 4 のデプロイ検証手順に含める。

- [ ] **Step 6: コミット**

```bash
git add nous/domain/tool_config.py nous/application/chat/tools/builtin.py nous/api/http/routers/image_gen.py nous/api/http/sections/chat/chat_sidebar_media.py nous/api/http/static/chat/chat-settings.js tests/unit/test_comfyui_provider.py
git commit -m "feat: wire workflow_source/workflow_name config through chat, HTTP and WebUI paths"
```

---

### Task 4: Dockerfile 修正・ドキュメント・NAS デプロイ手順

**Files:**
- Modify: `Dockerfile`（data/workflows/ の COPY を追加）
- Modify: `README.md`（画像生成設定セクションに追記）

- [ ] **Step 1: Dockerfile の COPY 行を確認**

Run: `grep -n "^COPY" Dockerfile`
Expected: `COPY data/skills/ data/skills/` 相当の行が見つかる（workflows の COPY が無いことを確認）

- [ ] **Step 2: Dockerfile を修正**

`COPY data/skills/ data/skills/` の直後に追加:

```dockerfile
COPY data/workflows/ data/workflows/
```

（同梱テンプレートがコンテナに入らない既知問題の修正。workflow_source="comfyui" 運用なら不要だが、local フォールバックと新規環境の初期セットアップ用。）

- [ ] **Step 3: README.md に設定ドキュメントを追記**

画像生成（ComfyUI）の節に以下を追記:

```markdown
### ComfyUI 保存ワークフローの直接実行

`image_gen_comfyui_workflow_source` を `"comfyui"` に設定すると、
ComfyUI 側の `user/default/workflows/` に保存済みのワークフローを
`/userdata` API で取得し、`/object_info` を併用して API 形式に変換して実行する。
Nous サーバー側にワークフローファイルを置く必要はない。

- `image_gen_comfyui_workflow_source`: `"local"`（既定・従来動作）| `"comfyui"`
- `image_gen_comfyui_workflow_name`: ComfyUI 側のワークフローファイル名（例: `"Anima_T2I_Turbo_Aesthetic.json"`）

変換時に UI ノードのタイトルが API 形式の `_meta.title` に写るため、
ノードタイトルに `NOUS:prompt` / `NOUS:negative_prompt` / `NOUS:reference_image` /
`NOUS:width` / `NOUS:height` / `NOUS:seed` / `NOUS:display` のタグを付ければ値の
注入が機能する。シードは毎回ランダム化され、`EmptyLatentImage` の width / height /
batch_size は実行時に上書きされる（`apply_generation_params`）。

モデル・LoRA・steps・cfg・sampler・scheduler・denoise はワークフロー側に埋め込む
（旧 `NOUS:checkpoint` / `NOUS:lora` / `NOUS:steps` / `NOUS:cfg` / `NOUS:sampler` /
`NOUS:scheduler` / `NOUS:denoise` タグと `image_gen_comfyui_checkpoint` 等の設定は廃止）。

対応外（現時点）: サブグラフ / V3 dynamic combo / GetNode-SetNode / bypass パススルー
を含むワークフロー。必要なら comfy-cli の変換器を移植する。
```

- [ ] **Step 4: コミット**

```bash
git add Dockerfile README.md
git commit -m "docs: document ComfyUI saved-workflow execution; fix Dockerfile workflows copy"
```

- [ ] **Step 5: NAS デプロイと実機検証（手動・ユーザー実施）**

1. リポジトリを NAS に反映し再ビルド:
   ```bash
   # NAS 上（\\nas\docker\nous）
   docker compose up -d --build nous
   ```
2. herta persona の設定を更新（`\\nas\docker\nous\data\persona\herta\config.json`）:
   ```json
   "image_gen_comfyui_workflow_source": "comfyui",
   "image_gen_comfyui_workflow_name": "Anima_T2I_Turbo_Aesthetic.json"
   ```
   ※ ワークフローファイルは ComfyUI 側 `D:\Application\ComfyUI\user\default\workflows\` に既存（Anima_T2I / Anima_I2I / Anima_I2I_FaceSwap の3点）。これで従来の「workflow_template 空文字」エラーも解消される（local ソースのときのみ必須のため）。
3. 動作確認（ComfyUI を起動した状態で）:
   ```bash
   curl -X POST http://localhost:26262/api/chat/herta/image-gen/test \
     -H "Content-Type: application/json" \
     -d '{"prompt": "The Herta, dancing, masterpiece, best quality, score_7, safe"}'
   ```
   Expected: `{"ok": true, "images": [...]}` — 生成画像の base64 が返る
4. 失敗時は ComfyUI 側ログ（`/history/{prompt_id}` の status）と Nous ログを確認。

---

## Self-Review 結果

- **Spec coverage:** ①「ComfyUI 側のワークフローを /userdata で取得」→ Task 2 `_fetch_userdata_workflow`。②「UI→API 変換」→ Task 1 `convert_ui_to_api`（/object_info 併用、comfy-cli パターン踏襲）。③「既存 NOUS: 注入との互換」→ 変換時に `_meta.title` へ title を写す＋Task 3 で設定配線。④「NAS のテンプレート欠落・空文字問題」→ Task 4 Step 5 で `workflow_source="comfyui"` 運用に切り替えて解消＋Dockerfile COPY 修正。⑤「パラメータ注入の廃止（ユーザー方針）」→ Task 2 で checkpoint/LoRA/steps/cfg/sampler/scheduler/denoise/seed 引数とタグ注入・LoRA チェーンを削除、Task 3 で ToolConfig・builtin・routers・WebUI フォームから除去。⑥「シード毎回ランダム化（ユーザー決定）」→ Task 1 Step 6 `apply_generation_params`（seed/noise_seed ランダム化＋EmptyLatentImage の width/height/batch_size 注入）。⑦「枚数 n=1〜4 残す（ユーザー決定）」→ `apply_generation_params` の batch_size 注入＋`_poll_result` の `images[:n]`（既存）。⑧「サイズ指定を残す（ユーザー決定）」→ preset 機構と `NOUS:width`/`NOUS:height`・EmptyLatentImage 注入を維持。
- **Placeholder scan:** コードブロックは全て実コード。`# ponytail:` コメントで対応外スコープを明示（Task 1 Step 4 の docstring 内に集約）。
- **Type consistency:** `apply_generation_params(workflow, *, width, height, n, seed)` のシグネチャは Task 1 Step 6 定義と Task 2 generate() の呼び出しで一致。`ComfyUIProvider` の新 __init__ シグネチャは Task 3 の builtin.py / routers 呼び出し（width/height/workflow_template/workflow_source/workflow_name/timeout_seconds のみ）と一致。ToolConfig フィールド名は builtin.py / routers / chat-settings.js のキーと一致。
- **確認済みの前提:** ComfyUI 0.31.0 の GET `/userdata/workflows/{name}.json` は user/default 相対で JSON 生内容を返す（exp-2/lib-2 調査）。Nous の ComfyUIProvider は httpx 非同期で `/prompt` は API 形式のみ受理（exp-1 調査・既存実装）。WebUI の保存は `chat_management.py` の動的フィールドマージ方式のため、ToolConfig の追加・削除だけで自動反映（exp-1 調査）。
