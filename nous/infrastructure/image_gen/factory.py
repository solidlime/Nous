from __future__ import annotations

from typing import TYPE_CHECKING

from .dalle import DalleProvider
from .stability import StabilityProvider

if TYPE_CHECKING:
    from .base import ImageGenConfig, ImageGenProvider


def get_image_gen_provider(config: ImageGenConfig) -> ImageGenProvider | None:
    """設定から画像生成プロバイダを生成。対応するプロバイダがない場合はNone"""
    if config.provider == "openai":
        return DalleProvider(model=config.dalle_model)
    elif config.provider == "stability":
        if not config.stability_url:
            return None
        return StabilityProvider(api_url=config.stability_url)
    elif config.provider == "comfyui":
        from .comfyui import ComfyUIProvider

        return ComfyUIProvider(api_url=config.comfyui_url)
    return None
