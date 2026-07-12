from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class GeneratedImage:
    """生成された画像"""

    base64: str  # base64エンコードされた画像データ
    revised_prompt: str  # DALL-Eが生成した場合の改訂プロンプト（SDでは元プロンプトをそのまま）
    size: str  # 画像サイズ (例: "1024x1024")


@dataclass
class ImageGenConfig:
    """画像生成設定"""

    provider: str = "openai"  # "openai" | "stability" | "comfyui"
    dalle_model: str = "dall-e-3"  # "dall-e-2" | "dall-e-3"
    stability_url: str = ""  # SD WebUI APIエンドポイント (例: http://localhost:7860)
    comfyui_url: str = "http://localhost:8188"  # ComfyUI APIエンドポイント
    size: str = "1024x1024"  # 画像サイズ (例: "1024x1024")
    quality: str = "standard"  # 品質 ("standard" | "hd")


class ImageGenProvider(ABC):
    """画像生成プロバイダの抽象基底クラス"""

    @abstractmethod
    async def generate(
        self,
        prompt: str,
        size: str = "1024x1024",
        quality: str = "standard",
        n: int = 1,
    ) -> list[GeneratedImage]:
        """
        画像を生成する。

        Args:
            prompt: 生成プロンプト
            size: 画像サイズ (DALL-E: "1024x1024"|"1792x1024"|"1024x1792", SD: "512x512"等)
            quality: 品質 (DALL-Eのみ: "standard"|"hd")
            n: 生成枚数 (1-4)

        Returns:
            生成された画像のリスト
        """
        ...

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """プロバイダ名 ("openai" または "stability")"""
        ...
