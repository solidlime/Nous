"""Tests for builtin.py tool handler parameter validation."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from nous.application.chat.tools.builtin import (
    _handle_image_generate,
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


@pytest.fixture
def mock_config():
    """Minimal ChatConfig mock."""
    cfg = MagicMock()
    cfg.image_gen_enabled = True
    cfg.image_gen_provider = "comfyui"
    cfg.image_gen_comfyui_url = ""
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
