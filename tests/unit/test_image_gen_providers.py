"""画像生成プロバイダの単体テスト"""

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# openai パッケージがインストールされていなくてもテスト可能にする
_FAKE_OPENAI = MagicMock()
if "openai" not in sys.modules:
    sys.modules["openai"] = _FAKE_OPENAI


# ============================================================
# DalleProvider テスト
# ============================================================


@pytest.mark.asyncio
async def test_dalle_generate_success():
    """DALL-E 3で画像生成が成功する"""
    mock_response = MagicMock()
    mock_response.data = [
        MagicMock(url="https://example.com/image1.png", revised_prompt="改訂されたプロンプト"),
    ]

    with patch("openai.AsyncOpenAI") as mock_client_class:
        mock_client = MagicMock()
        mock_client.images.generate = AsyncMock(return_value=mock_response)
        mock_client_class.return_value = mock_client

        with patch("httpx.AsyncClient") as mock_http_class:
            mock_http = MagicMock()
            mock_http.__aenter__.return_value = mock_http
            mock_resp = MagicMock()
            mock_resp.raise_for_status = MagicMock()
            mock_resp.content = b"fake_png_data"  # 適当なバイナリ
            mock_http.get = AsyncMock(return_value=mock_resp)
            mock_http_class.return_value = mock_http

            from nous.infrastructure.image_gen.dalle import DalleProvider

            provider = DalleProvider(model="dall-e-3")
            images = await provider.generate(prompt="かわいい猫", size="1024x1024")

            assert len(images) == 1
            assert images[0].revised_prompt == "改訂されたプロンプト"
            assert images[0].size == "1024x1024"
            assert isinstance(images[0].base64, str)
            assert len(images[0].base64) > 0


@pytest.mark.asyncio
async def test_dalle_generate_multiple():
    """DALL-E 3で複数枚生成"""
    mock_response = MagicMock()
    mock_response.data = [
        MagicMock(url=f"https://example.com/image{i}.png", revised_prompt=f"prompt{i}") for i in range(3)
    ]

    with patch("openai.AsyncOpenAI") as mock_client_class:
        mock_client = MagicMock()
        mock_client.images.generate = AsyncMock(return_value=mock_response)
        mock_client_class.return_value = mock_client

        with patch("httpx.AsyncClient") as mock_http_class:
            mock_http = MagicMock()
            mock_http.__aenter__.return_value = mock_http
            mock_resp = MagicMock()
            mock_resp.raise_for_status = MagicMock()
            mock_resp.content = b"fake_data"
            mock_http.get = AsyncMock(return_value=mock_resp)
            mock_http_class.return_value = mock_http

            from nous.infrastructure.image_gen.dalle import DalleProvider

            provider = DalleProvider()
            images = await provider.generate(prompt="test", n=3)

            assert len(images) == 3


@pytest.mark.asyncio
async def test_dalle_generate_api_error():
    """DALL-E 3 APIエラー時に例外が伝播する"""
    with patch("openai.AsyncOpenAI") as mock_client_class:
        mock_client = MagicMock()
        mock_client.images.generate = AsyncMock(side_effect=Exception("API Error"))
        mock_client_class.return_value = mock_client

        from nous.infrastructure.image_gen.dalle import DalleProvider

        provider = DalleProvider()

        with pytest.raises(Exception, match="API Error"):
            await provider.generate(prompt="test")


# ============================================================
# StabilityProvider テスト
# ============================================================


@pytest.mark.asyncio
async def test_stability_generate_success():
    """SD WebUIで画像生成が成功する"""
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {"images": ["base64string1", "base64string2"]}

    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = MagicMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client_class.return_value = mock_client

        from nous.infrastructure.image_gen.stability import StabilityProvider

        provider = StabilityProvider(api_url="http://localhost:7860")
        images = await provider.generate(prompt="test", size="512x512", n=1)

        assert len(images) == 2  # SDは1回のAPIコールで2枚返す
        assert images[0].base64 == "base64string1"
        assert images[1].base64 == "base64string2"


@pytest.mark.asyncio
async def test_stability_generate_multiple_n():
    """n>1の場合、複数回APIが呼ばれる"""
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {"images": ["img"]}

    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = MagicMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client_class.return_value = mock_client

        from nous.infrastructure.image_gen.stability import StabilityProvider

        provider = StabilityProvider(api_url="http://localhost:7860")
        images = await provider.generate(prompt="test", n=3)

        assert len(images) == 3
        assert mock_client.post.call_count == 3  # 3回呼ばれる


@pytest.mark.asyncio
async def test_stability_generate_connection_error():
    """SD WebUI接続エラー時"""
    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = MagicMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.post = AsyncMock(side_effect=Exception("Connection refused"))
        mock_client_class.return_value = mock_client

        from nous.infrastructure.image_gen.stability import StabilityProvider

        provider = StabilityProvider(api_url="http://localhost:7860")

        with pytest.raises(Exception, match="Connection refused"):
            await provider.generate(prompt="test")


# ============================================================
# Factory テスト
# ============================================================


def test_factory_returns_dalle_provider():
    """factoryがDALL-Eプロバイダを返す"""
    from nous.infrastructure.image_gen.base import ImageGenConfig
    from nous.infrastructure.image_gen.factory import get_image_gen_provider

    config = ImageGenConfig(provider="openai", dalle_model="dall-e-3")
    provider = get_image_gen_provider(config)

    assert provider is not None
    assert provider.provider_name == "openai"


def test_factory_returns_stability_provider():
    """factoryがSDプロバイダを返す"""
    from nous.infrastructure.image_gen.base import ImageGenConfig
    from nous.infrastructure.image_gen.factory import get_image_gen_provider

    config = ImageGenConfig(provider="stability", stability_url="http://localhost:7860")
    provider = get_image_gen_provider(config)

    assert provider is not None
    assert provider.provider_name == "stability"


def test_factory_returns_none_when_no_stability_url():
    """SD URLが設定されていない場合None"""
    from nous.infrastructure.image_gen.base import ImageGenConfig
    from nous.infrastructure.image_gen.factory import get_image_gen_provider

    config = ImageGenConfig(provider="stability", stability_url="")
    provider = get_image_gen_provider(config)

    assert provider is None


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
