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
    wf["nodes"].append(
        {
            "id": 30,
            "type": "UnknownCustomNodeXYZ",
            "title": "x",
            "mode": 0,
            "inputs": [],
            "outputs": [],
            "widgets_values": [1],
        }
    )
    api = convert_ui_to_api(wf, OBJECT_INFO)
    assert "30" not in api
    assert "6" in api


# --- 動的 LoRA スロット（rgthree Power Lora Loader 等）---


_RGTHREE_SCHEMA = {"input": {"required": {}, "optional": {}}, "output": ["LORA_STACK"]}
_OBJECT_INFO_WITH_RGTHREE = {"Power Lora Loader (rgthree)": _RGTHREE_SCHEMA}


def _rgthree_workflow(*, with_named: bool) -> dict:
    """実物ワークフローと同じ形状の合成ノード。"""
    node: dict = {
        "id": 18,
        "type": "Power Lora Loader (rgthree)",
        "title": "Power Lora Loader",
        "mode": 0,
        "inputs": [],
        "outputs": [],
        "properties": {},
        "widgets_values": [
            {},
            {"type": "PowerLoraLoaderHeaderWidget"},
            {"on": True, "lora": "Anima\\anima-turbo-lora-v0.2.safetensors", "strength": 0.65, "strengthTwo": None},
            {"on": True, "lora": "Anima\\The Herta.safetensors", "strength": 1, "strengthTwo": None},
            {"on": False, "lora": "Anima\\Koikatsu Style.safetensors", "strength": 1, "strengthTwo": None},
            {"on": True, "lora": "Anima\\@skintextureV1 3d skin.safetensors", "strength": 0.65, "strengthTwo": None},
            {},
            "",
        ],
    }
    if with_named:
        node["widgets_values_named"] = {
            "divider": {},
            "PowerLoraLoaderHeaderWidget": {"type": "PowerLoraLoaderHeaderWidget"},
            "lora_1": {"on": True, "lora": "a.safetensors", "strength": 0.65},
            "lora_2": {"on": False, "lora": "b.safetensors", "strength": 1},
            "➕ Add Lora": "",
        }
    return {"nodes": [node], "links": []}


def test_convert_rgthree_dynamic_lora_slots_from_widgets_values():
    """widgets_values の形状ベース救出: lora_1..4 が正しく入る（off スロットも送る）。"""
    api = convert_ui_to_api(_rgthree_workflow(with_named=False), _OBJECT_INFO_WITH_RGTHREE)
    slots = api["18"]["inputs"]
    assert slots["lora_1"]["lora"] == "Anima\\anima-turbo-lora-v0.2.safetensors"
    assert slots["lora_1"]["on"] is True
    assert slots["lora_1"]["strength"] == 0.65
    assert slots["lora_2"]["lora"] == "Anima\\The Herta.safetensors"
    assert slots["lora_3"]["on"] is False  # off も API エクスポートと同じく送信対象
    assert slots["lora_3"]["lora"] == "Anima\\Koikatsu Style.safetensors"
    assert slots["lora_4"]["lora"] == "Anima\\@skintextureV1 3d skin.safetensors"
    assert len(slots) == 4  # ヘッダー・空dict・文字列は lora_N にならない


def test_convert_rgthree_prefers_widgets_values_named_keys():
    """widgets_values_named（自己記述形式）があればそのキー名を優先する。"""
    api = convert_ui_to_api(_rgthree_workflow(with_named=True), _OBJECT_INFO_WITH_RGTHREE)
    slots = api["18"]["inputs"]
    assert slots["lora_1"]["lora"] == "a.safetensors"
    assert slots["lora_2"]["on"] is False
    assert len(slots) == 2


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
