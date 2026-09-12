"""MCPツール・画像生成設定 — ToolConfig.

ChatConfig から分割された、MCPツール・画像生成に関する設定を保持する。
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ToolConfig(BaseModel):
    """MCPツール・画像生成設定。"""

    # MCP / ツール設定
    mcp_servers: list[dict] = Field(default=[], description="接続するMCPサーバーの定義。")
    enabled_skills: list[str] = Field(default=[], description="有効にするスキルの一覧。")
    disabled_tools: list[str] = Field(default=[], description="無効にするツールの一覧。")
    enable_parallel_tools: bool = Field(default=True, description="複数のツールを並列実行します。")
    dynamic_tool_selection: bool = Field(default=True, description="ターンごとに必要なツールを動的に選択します。")
    enable_memory_tools: bool = Field(default=True, description="AIが記憶を操作するツールを使えるようにします。")

    # 画像生成
    image_gen_enabled: bool = Field(default=False, description="画像生成機能を有効にします。")
    image_gen_provider: str = Field(default="comfyui", description="画像生成に使うプロバイダー。")
    image_gen_comfyui_url: str = Field(default="", description="ComfyUIサーバーのURL。")  # ComfyUI APIエンドポイント
    # ComfyUI 詳細設定
    image_gen_comfyui_width: int = Field(default=1024, description="生成画像の幅（px）。")
    image_gen_comfyui_height: int = Field(default=1024, description="生成画像の高さ（px）。")
    image_gen_comfyui_timeout_seconds: int = Field(default=180, description="画像生成のタイムアウト（秒）。")  # 生成タイムアウト（秒）
    image_gen_comfyui_workflow_template: str = Field(
        default="workflows/anima.json",  # path to API-format JSON workflow template (required; empty raises in ComfyUIProvider)
        description="使用するワークフローテンプレートのパス。",
    )
    image_gen_comfyui_workflow_source: str = Field(
        default="local",  # "local" | "comfyui"（ComfyUI 側 user/default/workflows から取得）
        description="ワークフローの取得元（local / comfyui）。",
    )
    image_gen_comfyui_workflow_name: str = Field(default="", description="ComfyUI側のワークフロー名。")  # workflow_source="comfyui" 時の ComfyUI 側ワークフローファイル名
    image_gen_max_width: int = Field(default=1200, description="生成画像の最大幅（px）。")
    image_gen_max_height: int = Field(default=1200, description="生成画像の最大高さ（px）。")
    # 画像生成プリセット（preset名 → "WxH"）
    image_gen_presets: dict[str, str] = Field(
        default={
            "portrait_large": "832x1216",
            "portrait_medium": "768x1024",
            "portrait_small": "576x768",
            "landscape_large": "1216x832",
            "landscape_medium": "1024x768",
            "landscape_small": "768x576",
            "square_large": "1024x1024",
            "square_medium": "768x768",
            "square_small": "512x512",
        },
        description="プリセット解像度（名前→WxH）の一覧。",
    )
    image_gen_default_preset: str = Field(default="square_medium", description="既定で使う解像度プリセット。")
    # 自画像生成用プロンプト（キャラ外見のSDタグ・LoRAトリガーワード・トーンなどを含む固定プロンプト文字列）
    image_gen_self_portrait_prompt: str = Field(default="", description="自画像生成に使う固定プロンプト。")
    image_gen_negative_prompt: str = Field(default="", description="生成から除外したい内容（ネガティブプロンプト）。")  # negative prompt for image generation
    image_gen_full_body_prefix: str = Field(default="full body, standing, pov, ", description="全身構図のプロンプト接頭辞。")
    image_gen_portrait_prefix: str = Field(default="upper body, portrait, pov, ", description="上半身構図のプロンプト接頭辞。")
    image_gen_selfie_prefix: str = Field(default="selfie, from below, mirror selfie, ", description="自撮り構図のプロンプト接頭辞。")
    image_gen_scene_prefix: str = Field(default="environment shot, full body, ", description="情景構図のプロンプト接頭辞。")

    # Image caption (for non-vision providers)
    image_caption_enabled: bool = Field(default=True, description="画像をテキストで説明するキャプション機能を有効にします。")
    image_caption_provider: str = Field(default="openai_compat", description="キャプション生成に使うプロバイダー。")
    image_caption_model: str = Field(default="gpt-4o-mini", description="キャプション生成に使うモデル。")
    image_caption_api_key: str = Field(default="", description="キャプション生成のAPIキー。")
    image_caption_base_url: str = Field(default="", description="キャプション生成の接続先URL。")

    # Emotion decay config
    emotion_decay_half_life_hours: float | None = Field(default=None, description="感情価が半分に減衰するまでの時間。空欄でカテゴリ既定。")
    emotion_decay_threshold: float = Field(default=0.005, description="感情価を減衰とみなす下限しきい値。")
    emotion_neutral_threshold: float = Field(default=0.01, description="感情を中立とみなすしきい値。")
