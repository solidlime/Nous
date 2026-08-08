from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class GeneratedImage:
    """生成された画像"""

    base64: str  # base64エンコードされた画像データ
    revised_prompt: str  # プロバイダが修正したプロンプト（なければ元のまま）
    size: str  # 画像サイズ (例: "1024x1024")
    negative_prompt: str = ""  # ネガティブプロンプト（未指定時はプロバイダ標準値）
    node_id: str | None = None  # 出力ノードID (ComfyUI history outputs key)
    node_title: str | None = None  # 出力ノードのタイトル (_meta.title)
    display: bool = True  # NOUS:display タグによる表示対象か（False は保存・表示しない）


@dataclass
class ImageGenConfig:
    """画像生成設定"""

    provider: str = "comfyui"  # "comfyui" | "auto"
    comfyui_url: str = ""  # ComfyUI APIエンドポイント (caller must provide, no default here)
    timeout_seconds: float = 180.0  # 生成タイムアウト（秒）
    size: str = "1024x1024"  # 画像サイズ (例: "1024x1024")
    quality: str = "standard"  # 品質 ("standard" | "hd")
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
        negative_prompt: str = "",
        **kwargs: Any,
    ) -> list[GeneratedImage]:
        """
        画像を生成する。

        Args:
            prompt: 生成プロンプト
            size: 画像サイズ (例: "1024x1024")
            quality: 品質 ("standard"|"hd")
            n: 生成枚数 (1-4)
            reference_image: img2img用参照画像のバイト列 (Noneの場合はtxt2img)
            negative_prompt: ネガティブプロンプト（空文字の場合はプロバイダ標準値）

        Returns:
            生成された画像のリスト
        """
        ...

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """プロバイダ名 ("comfyui")"""
        ...
