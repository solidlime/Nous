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
        {
            "id": 10,
            "type": "Note",
            "title": "memo",
            "mode": 0,
            "inputs": [],
            "outputs": [],
            "widgets_values": ["hello"],
        },
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
                "model",
                "positive",
                "negative",
                "latent_image",
                "seed",
                "steps",
                "cfg",
                "sampler_name",
                "scheduler",
                "denoise",
            ],
            "optional": [],
        },
        "display_name": "KSampler",
    },
}
