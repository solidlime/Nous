"""Tests for _tool_persona_portrait — ChatConfig-based enabled check."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nous.domain.chat_config import ChatConfig


@pytest.fixture
def mock_ctx():
    ctx = MagicMock()
    ctx.settings.portrait_gen.enabled = False
    ctx.settings.portrait_gen.provider = "comfyui"
    ctx.settings.portrait_gen.comfyui_url = "http://localhost:8188"
    ctx.settings.portrait_gen.size = "512x512"
    ctx.settings.portrait_gen.quality = "standard"
    ctx.persona_service = MagicMock()
    ctx.persona_service.get_context = AsyncMock()
    ctx.connection.get_memory_db.return_value = MagicMock()
    return ctx


@pytest.fixture
def repo_patch():
    """Patch ChatConfigRepository.get() to return controlled ChatConfig."""
    with patch("nous.api.mcp._tools_portrait.ChatConfigRepository") as mock_repo_cls:
        mock_repo = MagicMock()
        mock_repo_cls.return_value = mock_repo
        yield mock_repo


class TestPortraitEnabled:
    """persona_portrait enabled check via ChatConfig with fallback to Settings."""

    async def test_portrait_disabled_returns_error(self, mock_ctx, repo_patch):
        """Both ChatConfig and Settings disabled → return error."""
        chat_config = ChatConfig(persona="test", portrait_enabled=False)
        repo_patch.get.return_value = chat_config

        from nous.api.mcp._tools_portrait import _tool_persona_portrait

        result = await _tool_persona_portrait(mock_ctx, "test")
        data = json.loads(result)
        assert data["ok"] is False
        assert "disabled" in data["error"].lower()

    async def test_portrait_enabled_via_chat_config(self, mock_ctx, repo_patch):
        """ChatConfig.portrait_enabled = True → enabled even if Settings disabled."""
        chat_config = ChatConfig(persona="test", portrait_enabled=True)
        repo_patch.get.return_value = chat_config

        state_result = MagicMock()
        state_result.is_ok = True
        state_result.value = MagicMock()
        state_result.value.emotion = "happy"
        mock_ctx.persona_service.get_context.return_value = state_result

        # Mock PortraitGenerationService to avoid actual generation
        with patch("nous.application.portrait.service.PortraitGenerationService") as mock_svc_cls:
            mock_svc = AsyncMock()
            mock_svc.generate.return_value = {"image_base64": "fake", "prompt": "test", "negative_prompt": ""}
            mock_svc_cls.return_value = mock_svc

            from nous.api.mcp._tools_portrait import _tool_persona_portrait

            result = await _tool_persona_portrait(mock_ctx, "test")
            data = json.loads(result)
            # With enabled=True, should succeed (no error)
            assert "error" not in data or "disabled" not in str(data.get("error", "")).lower()

    async def test_portrait_fallback_to_settings(self, mock_ctx, repo_patch):
        """ChatConfig default (False) but Settings enabled → enabled."""
        chat_config = ChatConfig(persona="test", portrait_enabled=False)
        repo_patch.get.return_value = chat_config
        mock_ctx.settings.portrait_gen.enabled = True  # Settings enables it

        state_result = MagicMock()
        state_result.is_ok = True
        state_result.value = MagicMock()
        state_result.value.emotion = "happy"
        mock_ctx.persona_service.get_context.return_value = state_result

        with patch("nous.application.portrait.service.PortraitGenerationService") as mock_svc_cls:
            mock_svc = AsyncMock()
            mock_svc.generate.return_value = {"image_base64": "fake", "prompt": "test", "negative_prompt": ""}
            mock_svc_cls.return_value = mock_svc

            from nous.api.mcp._tools_portrait import _tool_persona_portrait

            result = await _tool_persona_portrait(mock_ctx, "test")
            data = json.loads(result)
            assert "error" not in data or "disabled" not in str(data.get("error", "")).lower()
