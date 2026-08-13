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
    cfg.image_gen_max_width = 1200
    cfg.image_gen_max_height = 1200
    cfg.image_gen_presets = {"square_medium": "768x768", "portrait_medium": "768x1024"}
    cfg.image_gen_default_preset = "square_medium"
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
    async def test_image_invalid_size_format(self, mock_ctx, mock_config):
        """preset='nonexistent' → error (unknown preset)"""
        result = await _handle_image_generate(mock_ctx, mock_config, {"prompt": "a cat", "preset": "nonexistent"})
        assert result["status"] == "error"
        assert "Unknown preset" in result["message"]

    @pytest.mark.asyncio
    async def test_image_invalid_size_format_no_x(self, mock_ctx, mock_config):
        """preset='also-missing' → error (unknown preset, shows available list)"""
        result = await _handle_image_generate(mock_ctx, mock_config, {"prompt": "a cat", "preset": "also-missing"})
        assert result["status"] == "error"
        assert "Unknown preset" in result["message"]
        assert "square_medium" in result["message"]

    @pytest.mark.asyncio
    async def test_image_size_exceeds_limit(self, mock_ctx, mock_config, tmp_path):
        """preset size='2000x2000' → error でなく max 1200 にクランプされる"""
        from unittest.mock import AsyncMock, patch

        mock_config.image_gen_presets = {"huge": "2000x2000"}

        class FakeSettings:
            data_root = str(tmp_path)

        with (
            patch("nous.infrastructure.image_gen.comfyui.ComfyUIProvider") as mock_provider_cls,
            patch("nous.config.settings.get_settings", return_value=FakeSettings()),
        ):
            mock_provider = mock_provider_cls.return_value
            mock_provider.generate = AsyncMock(return_value=[])
            result = await _handle_image_generate(mock_ctx, mock_config, {"prompt": "a cat", "preset": "huge"})

        assert result["status"] == "success"
        assert mock_provider_cls.call_args.kwargs["width"] == 1200
        assert mock_provider_cls.call_args.kwargs["height"] == 1200

    @pytest.mark.asyncio
    async def test_image_invalid_n_type(self, mock_ctx, mock_config):
        """n='abc' → error"""
        result = await _handle_image_generate(mock_ctx, mock_config, {"prompt": "a cat", "n": "abc"})
        assert result["status"] == "error"
        assert "Invalid value for 'n'" in result["message"]
