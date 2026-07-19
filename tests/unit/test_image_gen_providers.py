"""画像生成プロバイダの単体テスト"""

from unittest.mock import MagicMock

import pytest


# ============================================================
# Factory テスト
# ============================================================


def test_factory_returns_none_for_unknown_provider():
    """不明なプロバイダはNone"""
    from nous.infrastructure.image_gen.base import ImageGenConfig
    from nous.infrastructure.image_gen.factory import get_image_gen_provider

    config = ImageGenConfig(provider="unknown")
    provider = get_image_gen_provider(config)

    assert provider is None


def test_factory_returns_comfyui_provider():
    """factoryがComfyUIプロバイダを返す"""
    from nous.infrastructure.image_gen.base import ImageGenConfig
    from nous.infrastructure.image_gen.factory import get_image_gen_provider

    config = ImageGenConfig(provider="comfyui", comfyui_url="http://comfyui:8188")
    provider = get_image_gen_provider(config)

    assert provider is not None
    assert provider.provider_name == "comfyui"



