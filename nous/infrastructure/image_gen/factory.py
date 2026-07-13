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
    elif config.provider == "gemini":
        return DalleProvider(
            provider_name="gemini",
            model=config.gemini_model,
            base_url="https://openrouter.ai/api/v1",
            api_key=config.gemini_api_key,
        )
    elif config.provider == "replicate":
        from .replicate import ReplicateProvider

        return ReplicateProvider(
            model=config.replicate_model,
            api_key=config.replicate_api_key,
        )
    elif config.provider == "pollinations":
        from .pollinations import PollinationsImageProvider

        return PollinationsImageProvider()
    return None
