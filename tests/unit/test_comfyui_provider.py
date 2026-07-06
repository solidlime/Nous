"""ComfyUIProvider の単体テスト"""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

# ============================================================
# Health check tests
# ============================================================


@pytest.mark.asyncio
async def test_health_check_returns_true_when_comfyui_responds():
    """ComfyUIが200を返すとhealth_checkがTrue"""
    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client_class.return_value = mock_client

        from nous.infrastructure.image_gen.comfyui import ComfyUIProvider

        provider = ComfyUIProvider(api_url="http://localhost:8188")
        result = await provider.health_check()

        assert result is True
        mock_client.get.assert_called_once_with("http://localhost:8188/system_stats")


@pytest.mark.asyncio
async def test_health_check_returns_false_on_connection_error():
    """ComfyUIに接続できないとhealth_checkがFalse"""
    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = MagicMock()
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))
        mock_client_class.return_value = mock_client

        from nous.infrastructure.image_gen.comfyui import ComfyUIProvider

        provider = ComfyUIProvider(api_url="http://localhost:8188")
        result = await provider.health_check()

        assert result is False


@pytest.mark.asyncio
async def test_health_check_returns_false_on_non_200():
    """ComfyUIが200以外を返すとhealth_checkがFalse"""
    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 503
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client_class.return_value = mock_client

        from nous.infrastructure.image_gen.comfyui import ComfyUIProvider

        provider = ComfyUIProvider(api_url="http://localhost:8188")
        result = await provider.health_check()

        assert result is False


# ============================================================
# Generate tests
# ============================================================


@pytest.mark.asyncio
async def test_generate_submits_workflow_and_returns_images():
    """generateがworkflowを送信し、ポーリングして画像を返す"""
    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = MagicMock()

        # POST /prompt レスポンス
        post_resp = MagicMock()
        post_resp.status_code = 200
        post_resp.json.return_value = {"prompt_id": "test-id-123"}

        # GET /history/test-id-123 — 初回は空、2回目で完了
        empty_hist = MagicMock()
        empty_hist.json.return_value = {}

        completed_hist = MagicMock()
        completed_hist.json.return_value = {
            "test-id-123": {
                "outputs": {
                    "9": {
                        "images": [
                            {"filename": "nous_portrait_0001.png", "type": "output"},
                        ],
                    },
                },
            },
        }

        # GET /view — 画像ダウンロード
        img_resp = MagicMock()
        img_resp.status_code = 200
        img_resp.content = b"fake_png_data"

        mock_client.post = AsyncMock(return_value=post_resp)
        mock_client.get = AsyncMock(side_effect=[empty_hist, completed_hist, img_resp])
        mock_client_class.return_value = mock_client

        from nous.infrastructure.image_gen.comfyui import ComfyUIProvider

        provider = ComfyUIProvider(api_url="http://localhost:8188")
        with patch("asyncio.sleep", new=AsyncMock(return_value=None)):
            images = await provider.generate(prompt="a cute cat", size="512x512", n=1)

        assert len(images) == 1
        assert images[0].size == "512x512"
        assert images[0].revised_prompt == "a cute cat"
        assert len(images[0].base64) > 0

        # POST /prompt が正しく呼ばれたことを確認
        post_call = mock_client.post.call_args
        assert post_call[0][0] == "http://localhost:8188/prompt"
        sent_workflow = post_call[1]["json"]["prompt"]
        assert sent_workflow["6"]["inputs"]["text"] == "a cute cat"


@pytest.mark.asyncio
async def test_generate_retries_on_connection_error():
    """generateが接続エラー時にリトライする"""
    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = MagicMock()
        post_resp = MagicMock()
        post_resp.status_code = 200
        post_resp.json.return_value = {"prompt_id": "test-id-456"}

        completed_hist = MagicMock()
        completed_hist.json.return_value = {
            "test-id-456": {
                "outputs": {
                    "9": {
                        "images": [{"filename": "out.png", "type": "output"}],
                    },
                },
            },
        }
        img_resp = MagicMock()
        img_resp.status_code = 200
        img_resp.content = b"fake_png_data"

        mock_client.post = AsyncMock(side_effect=[httpx.ConnectError("fail"), httpx.ConnectError("fail"), post_resp])
        mock_client.get = AsyncMock(side_effect=[completed_hist, img_resp])
        mock_client_class.return_value = mock_client

        from nous.infrastructure.image_gen.comfyui import ComfyUIProvider

        provider = ComfyUIProvider(api_url="http://localhost:8188")
        with patch("asyncio.sleep", new=AsyncMock(return_value=None)):
            await provider.generate(prompt="test", n=1)

        assert mock_client.post.call_count == 3  # 初回 + 2リトライ


@pytest.mark.asyncio
async def test_generate_raises_on_all_retries_fail():
    """全リトライが失敗すると例外が上がる"""
    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = MagicMock()
        mock_client.post = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))
        mock_client_class.return_value = mock_client

        from nous.infrastructure.image_gen.comfyui import ComfyUIProvider

        provider = ComfyUIProvider(api_url="http://localhost:8188")

        with pytest.raises(RuntimeError, match="ComfyUI generation failed after retries"):
            await provider.generate(prompt="test", n=1)

        assert mock_client.post.call_count == 3


@pytest.mark.asyncio
async def test_generate_times_out_after_180s():
    """generateが180秒でタイムアウトする"""
    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = MagicMock()

        post_resp = MagicMock()
        post_resp.status_code = 200
        post_resp.json.return_value = {"prompt_id": "timeout-id"}

        # 常に空の履歴を返す
        empty_hist = MagicMock()
        empty_hist.json.return_value = {}

        mock_client.post = AsyncMock(return_value=post_resp)
        mock_client.get = AsyncMock(return_value=empty_hist)
        mock_client_class.return_value = mock_client

        from nous.infrastructure.image_gen.comfyui import ComfyUIProvider

        provider = ComfyUIProvider(api_url="http://localhost:8188")

        with (
            patch("asyncio.sleep", new=AsyncMock(return_value=None)),
            pytest.raises(RuntimeError, match="ComfyUI generation timed out"),
        ):
            await provider.generate(prompt="test", n=1)


@pytest.mark.asyncio
async def test_generate_multiple_images():
    """n>1で複数枚生成できる"""
    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = MagicMock()

        post_resp = MagicMock()
        post_resp.status_code = 200
        post_resp.json.return_value = {"prompt_id": "multi-id"}

        completed_hist = MagicMock()
        completed_hist.json.return_value = {
            "multi-id": {
                "outputs": {
                    "9": {
                        "images": [
                            {"filename": "nous_portrait_0001.png", "type": "output"},
                            {"filename": "nous_portrait_0002.png", "type": "output"},
                        ],
                    },
                },
            },
        }

        img_resp = MagicMock()
        img_resp.status_code = 200
        img_resp.content = b"fake_png_data"

        mock_client.post = AsyncMock(return_value=post_resp)
        mock_client.get = AsyncMock(side_effect=[completed_hist, img_resp, img_resp])
        mock_client_class.return_value = mock_client

        from nous.infrastructure.image_gen.comfyui import ComfyUIProvider

        provider = ComfyUIProvider(api_url="http://localhost:8188")
        with patch("asyncio.sleep", new=AsyncMock(return_value=None)):
            images = await provider.generate(prompt="test", n=2)

        assert len(images) == 2


# ============================================================
# Workflow build tests
# ============================================================


def test_build_workflow_512x512():
    """512x512のワークフローが正しく構築される"""
    from nous.infrastructure.image_gen.comfyui import ComfyUIProvider

    provider = ComfyUIProvider()
    workflow = provider._build_workflow("cat", "512x512", 1)

    assert workflow["5"]["inputs"]["width"] == 512
    assert workflow["5"]["inputs"]["height"] == 512
    assert workflow["5"]["inputs"]["batch_size"] == 1
    assert workflow["6"]["inputs"]["text"] == "cat"


def test_build_workflow_1024x1024():
    """1024x1024のワークフローが正しく構築される"""
    from nous.infrastructure.image_gen.comfyui import ComfyUIProvider

    provider = ComfyUIProvider()
    workflow = provider._build_workflow("dog", "1024x1024", 3)

    assert workflow["5"]["inputs"]["width"] == 1024
    assert workflow["5"]["inputs"]["height"] == 1024
    assert workflow["5"]["inputs"]["batch_size"] == 3


def test_provider_name():
    """provider_nameがcomfyuiを返す"""
    from nous.infrastructure.image_gen.comfyui import ComfyUIProvider

    provider = ComfyUIProvider()
    assert provider.provider_name == "comfyui"
