"""画像生成プロバイダの単体テスト"""




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


def test_factory_passes_timeout_seconds():
    """factory が config.timeout_seconds を ComfyUIProvider へ渡す"""
    from nous.infrastructure.image_gen.base import ImageGenConfig
    from nous.infrastructure.image_gen.factory import get_image_gen_provider

    config = ImageGenConfig(provider="comfyui", comfyui_url="http://comfyui:8188", timeout_seconds=42.0)
    provider = get_image_gen_provider(config)

    assert provider._timeout_seconds == 42.0


def test_factory_timeout_seconds_default_180():
    """config に timeout_seconds が無ければデフォルト 180"""
    from nous.infrastructure.image_gen.base import ImageGenConfig
    from nous.infrastructure.image_gen.factory import get_image_gen_provider

    config = ImageGenConfig(provider="comfyui", comfyui_url="http://comfyui:8188")
    provider = get_image_gen_provider(config)

    assert provider._timeout_seconds == 180.0



