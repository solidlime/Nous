"""MCPツール・画像生成設定 — ToolConfig.

ChatConfig から分割された、MCPツール・画像生成に関する設定を保持する。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class ToolConfig(BaseModel):
    """MCPツール・画像生成設定。"""

    # MCP / ツール設定
    mcp_servers: list[dict] = []
    enabled_skills: list[str] = []
    disabled_tools: list[str] = []
    enable_parallel_tools: bool = True
    dynamic_tool_selection: bool = True
    enable_memory_tools: bool = True

    # 画像生成
    image_gen_enabled: bool = False
    image_gen_provider: str = "comfyui"
    image_gen_comfyui_url: str = ""  # ComfyUI APIエンドポイント
    # ComfyUI 詳細設定
    image_gen_comfyui_checkpoint: str = ""
    image_gen_comfyui_loras: str = "[]"
    image_gen_comfyui_width: int = 1024
    image_gen_comfyui_height: int = 1024
    image_gen_comfyui_steps: int = 28
    image_gen_comfyui_cfg: float = 5.5
    image_gen_comfyui_sampler: str = "euler_ancestral"
    image_gen_comfyui_scheduler: str = "normal"
    image_gen_comfyui_seed: int = 0  # 0=ランダム
    image_gen_comfyui_denoise: float = 0.7
    # Generation mode: t2i (text-to-image) or i2i (image-to-image with reference)
    image_gen_mode: Literal["t2i", "i2i"] = "t2i"
    image_gen_max_width: int = 1200
    image_gen_max_height: int = 1200
    # 画像生成プリセット（preset名 → "WxH"）
    image_gen_presets: dict[str, str] = {
        "portrait_large": "832x1216",
        "portrait_medium": "768x1024",
        "portrait_small": "576x768",
        "landscape_large": "1216x832",
        "landscape_medium": "1024x768",
        "landscape_small": "768x576",
        "square_large": "1024x1024",
        "square_medium": "768x768",
        "square_small": "512x512",
    }
    image_gen_default_preset: str = "square_medium"
    # 自画像生成用プロンプト（キャラ外見のSDタグ・LoRAトリガーワード・トーンなどを含む固定プロンプト文字列）
    image_gen_self_portrait_prompt: str = ""
    image_gen_negative_prompt: str = ""  # negative prompt for image generation
    image_gen_full_body_prefix: str = "full body, standing, looking at viewer, "
    image_gen_portrait_prefix: str = "upper body, portrait, looking at viewer, "
    image_gen_selfie_prefix: str = "selfie, from below, mirror selfie, "
    image_gen_scene_prefix: str = "environment shot, full body, "
    # チャット背景画像・立ち絵
    chat_background_url: str = ""
    chat_background_dark_url: str = ""
    standing_pic_url: str = ""

    # Image caption (for non-vision providers)
    image_caption_enabled: bool = True
    image_caption_provider: str = "openai_compat"
    image_caption_model: str = "gpt-4o-mini"
    image_caption_api_key: str = ""
    image_caption_base_url: str = ""

    # Emotion decay config
    emotion_decay_half_life_hours: float = 24.0
    emotion_decay_threshold: float = 0.005
    emotion_neutral_threshold: float = 0.01

    # 高速化 LoRA
    image_gen_comfyui_speed_lora_path: str = "lcm_lora_sdxl.safetensors"
    image_gen_comfyui_speed_lora_weight: float = 1.0
    image_gen_comfyui_speed_lora_method: str = "lcm"  # lcm, lightning, hyper, tcd
