from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class GeneratedImage:
    """生成された画像"""

    base64: str  # base64エンコードされた画像データ
    revised_prompt: str  # DALL-Eが生成した場合の改訂プロンプト（SDでは元プロンプトをそのまま）
    size: str  # 画像サイズ (例: "1024x1024")


@dataclass
class ImageGenConfig:
    """画像生成設定"""

    provider: str = "openai"  # "openai" | "stability" | "comfyui" | "gemini" | "replicate"
    dalle_model: str = "dall-e-3"  # "dall-e-2" | "dall-e-3"
    stability_url: str = ""  # SD WebUI APIエンドポイント (例: http://localhost:7860)
    comfyui_url: str = ""  # ComfyUI APIエンドポイント (caller must provide, no default here)
    size: str = "1024x1024"  # 画像サイズ (例: "1024x1024")
    quality: str = "standard"  # 品質 ("standard" | "hd")
    # Gemini (OpenRouter経由)
    gemini_model: str = "google/gemini-2.5-flash-image"
    gemini_api_key: str = ""
    # Replicate (FLUX Schnell)
    replicate_model: str = "black-forest-labs/flux-schnell"
    replicate_api_key: str = ""
    # Reference image (img2img) support
    reference_image_enabled: bool = False  # True の場合reference_imageを受け付ける


class ImageGenProvider(ABC):
    """画像生成プロバイダの抽象基底クラス"""

    @abstractmethod
    async def generate(
        self,
        prompt: str,
        size: str = "1024x1024",
        quality: str = "standard",
        n: int = 1,
        reference_image: bytes | None = None,
        **kwargs: Any,
    ) -> list[GeneratedImage]:
        """
        画像を生成する。

        Args:
            prompt: 生成プロンプト
            size: 画像サイズ (DALL-E: "1024x1024"|"1792x1024"|"1024x1792", SD: "512x512"等)
            quality: 品質 (DALL-Eのみ: "standard"|"hd")
            n: 生成枚数 (1-4)
            reference_image: img2img用参照画像のバイト列 (Noneの場合はtxt2img)

        Returns:
            生成された画像のリスト
        """
        ...

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """プロバイダ名 ("openai" / "stability" / "comfyui" / "gemini" / "replicate")"""
        ...
