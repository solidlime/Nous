"""Tests for builtin.py tool handler parameter validation."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nous.application.chat.tools.builtin import (
    _handle_image_generate,
    _handle_search,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_ctx():
    """Minimal AppContext mock."""
    ctx = MagicMock()
    ctx.persona = "test_persona"
    ctx.settings = MagicMock()
    ctx.event_bus = AsyncMock()
    return ctx


@pytest.fixture(autouse=True)
def mock_runtime_config():
    """Patch RuntimeConfigManager to return test searxng URL."""
    with patch("nous.application.chat.tools.builtin.RuntimeConfigManager") as mock:
        mock.return_value.get_effective_value.return_value = ("http://test-searxng:11111", "env")
        yield


@pytest.fixture
def mock_config():
    """Minimal ChatConfig mock."""
    cfg = MagicMock()
    cfg.image_gen_enabled = True
    cfg.image_gen_provider = "openai"
    cfg.image_gen_dalle_model = "dall-e-3"
    cfg.image_gen_stability_url = ""
    return cfg


# ===================================================================
# _handle_image_generate
# ===================================================================


class TestImageGenerateHandler:
    @pytest.mark.asyncio
    async def test_image_disabled(self, mock_ctx, mock_config):
        """image_gen_enabled=False → error"""
        mock_config.image_gen_enabled = False
        result = await _handle_image_generate(mock_ctx, mock_config, {})
        assert result["status"] == "error"
        assert "disabled" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_image_empty_prompt(self, mock_ctx, mock_config):
        """prompt無指定 → error"""
        result = await _handle_image_generate(mock_ctx, mock_config, {})
        assert result["status"] == "error"
        assert "No prompt" in result["message"]

    @pytest.mark.asyncio
    async def test_image_empty_prompt_string(self, mock_ctx, mock_config):
        """prompt="" → error"""
        result = await _handle_image_generate(mock_ctx, mock_config, {"prompt": ""})
        assert result["status"] == "error"
        assert "No prompt" in result["message"]

    @pytest.mark.asyncio
    async def test_image_whitespace_prompt(self, mock_ctx, mock_config):
        """prompt="   " → error"""
        result = await _handle_image_generate(mock_ctx, mock_config, {"prompt": "   "})
        assert result["status"] == "error"
        assert "No prompt" in result["message"]

    @pytest.mark.asyncio
    async def test_image_invalid_provider(self, mock_ctx, mock_config):
        """provider="unknown" → error"""
        result = await _handle_image_generate(mock_ctx, mock_config, {"prompt": "a cat", "provider": "unknown"})
        assert result["status"] == "error"
        assert "Unsupported provider" in result["message"]

    @pytest.mark.asyncio
    async def test_image_stability_no_url(self, mock_ctx, mock_config):
        """provider="stability" with no URL configured → error"""
        result = await _handle_image_generate(mock_ctx, mock_config, {"prompt": "a cat", "provider": "stability"})
        assert result["status"] == "error"
        assert "URL" in result["message"]

    @pytest.mark.asyncio
    async def test_image_openai_call(self, mock_ctx, mock_config):
        """provider="openai" → DalleProvider generateが呼ばれる"""
        mock_provider = AsyncMock()
        mock_provider.provider_name = "openai"
        mock_provider.generate.return_value = []

        with (
            patch("nous.infrastructure.image_gen.dalle.DalleProvider", return_value=mock_provider) as mock_dalle,
        ):
            result = await _handle_image_generate(mock_ctx, mock_config, {"prompt": "a cat", "provider": "openai"})

        assert result["status"] == "success"
        mock_dalle.assert_called_once_with(model="dall-e-3")
        mock_provider.generate.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_image_openai_call_with_auto(self, mock_ctx, mock_config):
        """provider="auto" → configのprovider (openai) が使われる"""
        mock_provider = AsyncMock()
        mock_provider.provider_name = "openai"
        mock_provider.generate.return_value = []

        with patch("nous.infrastructure.image_gen.dalle.DalleProvider", return_value=mock_provider) as mock_dalle:
            result = await _handle_image_generate(mock_ctx, mock_config, {"prompt": "a cat", "provider": "auto"})

        assert result["status"] == "success"
        mock_dalle.assert_called_once_with(model="dall-e-3")

    @pytest.mark.asyncio
    async def test_image_stability_call(self, mock_ctx, mock_config):
        """provider="stability" with URL → StabilityProvider generateが呼ばれる"""
        mock_config.image_gen_stability_url = "http://sd:7860"
        mock_provider = AsyncMock()
        mock_provider.provider_name = "stability"
        mock_provider.generate.return_value = []

        with (
            patch("nous.infrastructure.image_gen.stability.StabilityProvider", return_value=mock_provider) as mock_sd,
        ):
            result = await _handle_image_generate(mock_ctx, mock_config, {"prompt": "a cat", "provider": "stability"})

        assert result["status"] == "success"
        mock_sd.assert_called_once_with(api_url="http://sd:7860")
        mock_provider.generate.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_image_n_clamp_low(self, mock_ctx, mock_config):
        """n=0 → clamp to 1"""
        mock_provider = AsyncMock()
        mock_provider.provider_name = "openai"
        mock_provider.generate.return_value = []

        with patch("nous.infrastructure.image_gen.dalle.DalleProvider", return_value=mock_provider):
            result = await _handle_image_generate(
                mock_ctx, mock_config, {"prompt": "a cat", "provider": "openai", "n": 0}
            )

        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_image_n_clamp_high(self, mock_ctx, mock_config):
        """n=10 → clamp to 4"""
        mock_provider = AsyncMock()
        mock_provider.provider_name = "openai"
        mock_provider.generate.return_value = []

        with patch("nous.infrastructure.image_gen.dalle.DalleProvider", return_value=mock_provider):
            result = await _handle_image_generate(
                mock_ctx, mock_config, {"prompt": "a cat", "provider": "openai", "n": 10}
            )

        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_image_openai_dalle_model_config(self, mock_ctx, mock_config):
        """configのdalle_modelがDalleProviderに伝搬する"""
        mock_config.image_gen_dalle_model = "dall-e-2"
        mock_provider = AsyncMock()
        mock_provider.provider_name = "openai"
        mock_provider.generate.return_value = []

        with patch("nous.infrastructure.image_gen.dalle.DalleProvider", return_value=mock_provider) as mock_dalle:
            result = await _handle_image_generate(mock_ctx, mock_config, {"prompt": "a cat", "provider": "openai"})

        assert result["status"] == "success"
        mock_dalle.assert_called_once_with(model="dall-e-2")

    # ── New validation tests ──

    @pytest.mark.asyncio
    async def test_image_invalid_size_format(self, mock_ctx, mock_config):
        """size='abc' → error (format validation)"""
        result = await _handle_image_generate(mock_ctx, mock_config, {"prompt": "a cat", "size": "abc"})
        assert result["status"] == "error"
        assert "Invalid size format" in result["message"]

    @pytest.mark.asyncio
    async def test_image_invalid_size_format_no_x(self, mock_ctx, mock_config):
        """size='1024-768' → error (format validation)"""
        result = await _handle_image_generate(mock_ctx, mock_config, {"prompt": "a cat", "size": "1024-768"})
        assert result["status"] == "error"
        assert "Invalid size format" in result["message"]

    @pytest.mark.asyncio
    async def test_image_unsupported_size(self, mock_ctx, mock_config):
        """size='200x200' → error (unsupported)"""
        result = await _handle_image_generate(mock_ctx, mock_config, {"prompt": "a cat", "size": "200x200"})
        assert result["status"] == "error"
        assert "Unsupported size" in result["message"]

    @pytest.mark.asyncio
    async def test_image_invalid_quality(self, mock_ctx, mock_config):
        """quality='premium' → error"""
        result = await _handle_image_generate(mock_ctx, mock_config, {"prompt": "a cat", "quality": "premium"})
        assert result["status"] == "error"
        assert "Unsupported quality" in result["message"]

    @pytest.mark.asyncio
    async def test_image_invalid_n_type(self, mock_ctx, mock_config):
        """n='abc' → error"""
        result = await _handle_image_generate(mock_ctx, mock_config, {"prompt": "a cat", "n": "abc"})
        assert result["status"] == "error"
        assert "Invalid value for 'n'" in result["message"]


# ===================================================================
# _handle_search
# ===================================================================


class TestSearchHandler:
    @pytest.mark.asyncio
    async def test_search_empty_query(self, mock_ctx, mock_config):
        """query無指定 → error"""
        result = await _handle_search(mock_ctx, mock_config, {})
        assert result["status"] == "error"
        assert "query" in result["message"]

    @pytest.mark.asyncio
    async def test_search_blank_query(self, mock_ctx, mock_config):
        """query="" → error"""
        result = await _handle_search(mock_ctx, mock_config, {"query": ""})
        assert result["status"] == "error"
        assert "query" in result["message"]

    @pytest.mark.asyncio
    async def test_search_whitespace_query(self, mock_ctx, mock_config):
        """query="   " → error"""
        result = await _handle_search(mock_ctx, mock_config, {"query": "   "})
        assert result["status"] == "error"
        assert "query" in result["message"]

    @pytest.mark.asyncio
    async def test_search_num_results_default(self, mock_ctx, mock_config):
        """num_results未指定 → デフォルト10件に制限"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "results": [
                {"title": f"Result {i}", "url": f"http://example.com/{i}", "content": f"Content {i}"} for i in range(20)
            ]
        }

        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.get.return_value = mock_response

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await _handle_search(mock_ctx, mock_config, {"query": "test"})

        assert result["status"] == "ok"
        assert len(result["results"]) == 10  # default limit

    @pytest.mark.asyncio
    async def test_search_num_results_explicit(self, mock_ctx, mock_config):
        """num_results=3 → 3件に制限"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "results": [
                {"title": f"Result {i}", "url": f"http://example.com/{i}", "content": f"Content {i}"} for i in range(20)
            ]
        }

        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.get.return_value = mock_response

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await _handle_search(mock_ctx, mock_config, {"query": "test", "num_results": 3})

        assert result["status"] == "ok"
        assert len(result["results"]) == 3

    @pytest.mark.asyncio
    async def test_search_with_language(self, mock_ctx, mock_config):
        """language="en" → URLにlanguage=enが含まれる"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"results": []}

        captured_url = None

        async def capture_get(url, **kwargs):
            nonlocal captured_url
            captured_url = url
            return mock_response

        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.get = capture_get

        with patch("httpx.AsyncClient", return_value=mock_client):
            await _handle_search(mock_ctx, mock_config, {"query": "test", "language": "en"})

        assert captured_url is not None
        assert "language=en" in captured_url

    @pytest.mark.asyncio
    async def test_search_default_language(self, mock_ctx, mock_config):
        """language未指定 → デフォルトja"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"results": []}

        captured_url = None

        async def capture_get(url, **kwargs):
            nonlocal captured_url
            captured_url = url
            return mock_response

        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.get = capture_get

        with patch("httpx.AsyncClient", return_value=mock_client):
            await _handle_search(mock_ctx, mock_config, {"query": "test"})

        assert captured_url is not None
        assert "language=ja" in captured_url

    @pytest.mark.asyncio
    async def test_search_httpx_call(self, mock_ctx, mock_config):
        """正常系 → httpxで結果取得"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "results": [
                {"title": "Test Result", "url": "http://example.com", "content": "Test content."},
            ]
        }

        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await _handle_search(mock_ctx, mock_config, {"query": "test query"})

        assert result["status"] == "ok"
        assert result["query"] == "test query"
        assert len(result["results"]) == 1
        assert result["results"][0]["title"] == "Test Result"
        assert result["count"] == 1

    @pytest.mark.asyncio
    async def test_search_httpx_timeout(self, mock_ctx, mock_config):
        """httpx.TimeoutException → error"""
        import httpx

        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.get = AsyncMock(side_effect=httpx.TimeoutException("timeout"))

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await _handle_search(mock_ctx, mock_config, {"query": "test"})

        assert result["status"] == "error"
        assert "timed out" in result["message"]

    @pytest.mark.asyncio
    async def test_search_httpx_connect_error(self, mock_ctx, mock_config):
        """httpx.ConnectError → error"""
        import httpx

        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("connection refused"))

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await _handle_search(mock_ctx, mock_config, {"query": "test"})

        assert result["status"] == "error"
        assert "connection failed" in result["message"] or "ConnectError" in result["message"]

    @pytest.mark.asyncio
    async def test_search_httpx_http_error(self, mock_ctx, mock_config):
        """httpx.HTTPStatusError → error"""
        import httpx

        resp_mock = MagicMock()
        resp_mock.status_code = 500
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.get = AsyncMock(
            side_effect=httpx.HTTPStatusError("server error", request=MagicMock(), response=resp_mock)
        )

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await _handle_search(mock_ctx, mock_config, {"query": "test"})

        assert result["status"] == "error"
        assert "HTTP" in result["message"]

    @pytest.mark.asyncio
    async def test_search_empty_results_list(self, mock_ctx, mock_config):
        """空の結果リスト → ok、count=0"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"results": []}

        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await _handle_search(mock_ctx, mock_config, {"query": "nothing"})

        assert result["status"] == "ok"
        assert result["count"] == 0
        assert result["results"] == []
