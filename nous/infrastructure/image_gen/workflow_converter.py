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
import random
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
        if node_type not in object_info:
            # /object_info に無いノード型はスキップ（ComfyUI に未ロードの型は実行不能）
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
