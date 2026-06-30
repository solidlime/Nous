"""Tests for ImageGenHealthChecker — ComfyUI connection health check."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nous.infrastructure.image_gen.health import ImageGenHealthChecker


@pytest.mark.asyncio
async def test_check_returns_true_on_200():
    """check() returns True when ComfyUI responds with 200."""
    checker = ImageGenHealthChecker(comfyui_url="http://localhost:8188")

    mock_response = MagicMock()
    mock_response.status_code = 200

    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = MagicMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client_class.return_value = mock_client

        result = await checker.check()

    assert result is True
    assert checker._last_status is True


@pytest.mark.asyncio
async def test_check_returns_false_on_connection_error():
    """check() returns False when ComfyUI is unreachable."""
    checker = ImageGenHealthChecker(comfyui_url="http://localhost:8188")

    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = MagicMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.get = AsyncMock(side_effect=ConnectionError("Connection refused"))
        mock_client_class.return_value = mock_client

        result = await checker.check()

    assert result is False
    assert checker._last_status is False


def test_is_available_reflects_last_check_result():
    """is_available returns True only after a successful check."""
    checker = ImageGenHealthChecker(comfyui_url="http://localhost:8188")

    # Initially None — not available
    assert checker.is_available is False

    # Simulate successful check
    checker._last_status = True
    assert checker.is_available is True

    # Simulate failed check
    checker._last_status = False
    assert checker.is_available is False


def test_get_fallback_message_on_unavailable():
    """get_fallback_message returns message when unavailable."""
    checker = ImageGenHealthChecker(comfyui_url="http://localhost:8188")

    # When _last_status is None (never checked)
    assert checker.get_fallback_message() == ""

    # When available
    checker._last_status = True
    assert checker.get_fallback_message() == ""

    # When unavailable
    checker._last_status = False
    msg = checker.get_fallback_message()
    assert "ComfyUI is unreachable" in msg
    assert "emotion icon fallback" in msg


@pytest.mark.asyncio
async def test_check_url_ends_with_system_stats():
    """check() hits the correct endpoint path."""
    checker = ImageGenHealthChecker(comfyui_url="http://localhost:8188")

    mock_response = MagicMock()
    mock_response.status_code = 200

    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = MagicMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client_class.return_value = mock_client

        await checker.check()

    # Verify the correct URL was called
    mock_client.get.assert_called_once_with("http://localhost:8188/system_stats")
