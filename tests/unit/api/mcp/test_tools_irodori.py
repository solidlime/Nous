"""Tests for _tool_irodori_tts — ChatConfig-based enabled check."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nous.domain.chat_config import ChatConfig


@pytest.fixture
def mock_ctx():
    ctx = MagicMock()
    ctx.settings.irodori.enabled = False
    ctx.settings.irodori.url = "http://irodori:8088/v1"
    ctx.settings.irodori.voice = "default"
    ctx.settings.irodori.timeout_seconds = 30
    ctx.persona_service = MagicMock()
    ctx.persona_service.get_context = AsyncMock()
    ctx.connection.get_memory_db.return_value = MagicMock()
    return ctx


@pytest.fixture
def repo_patch():
    """Patch ChatConfigRepository.get() to return controlled ChatConfig."""
    with patch("nous.api.mcp._tools_irodori.ChatConfigRepository") as mock_repo_cls:
        mock_repo = MagicMock()
        mock_repo_cls.return_value = mock_repo
        yield mock_repo


class TestIrodoriEnabled:
    """irodori_tts enabled check via ChatConfig with fallback to Settings."""

    async def test_irodori_disabled_returns_error(self, mock_ctx, repo_patch):
        """Both ChatConfig and Settings disabled → return error."""
        chat_config = ChatConfig(persona="test", irodori_enabled=False)
        repo_patch.get.return_value = chat_config

        from nous.api.mcp._tools_irodori import _tool_irodori_tts

        result = await _tool_irodori_tts(mock_ctx, "test", "こんにちは")
        data = json.loads(result)
        assert data["ok"] is False
        assert "not enabled" in data["error"].lower()

    async def test_irodori_enabled_via_chat_config(self, mock_ctx, repo_patch):
        """ChatConfig.irodori_enabled = True → enabled even if Settings disabled."""
        chat_config = ChatConfig(persona="test", irodori_enabled=True)
        repo_patch.get.return_value = chat_config

        # Mock engine to avoid actual HTTP calls
        with patch("nous.infrastructure.voice.factory.get_voice_engine") as mock_get_engine:
            mock_engine = AsyncMock()
            mock_engine.health_check.return_value = True
            mock_engine.synthesize.return_value = b"fake_wav_data"
            mock_get_engine.return_value = mock_engine
            mock_engine._voice = "default"

            from nous.api.mcp._tools_irodori import _tool_irodori_tts

            result = await _tool_irodori_tts(mock_ctx, "test", "こんにちは")
            data = json.loads(result)
            assert data["ok"] is True
            assert "audio_base64" in data

    async def test_irodori_fallback_to_settings(self, mock_ctx, repo_patch):
        """ChatConfig default (False) but Settings enabled → enabled."""
        chat_config = ChatConfig(persona="test", irodori_enabled=False)
        repo_patch.get.return_value = chat_config
        mock_ctx.settings.irodori.enabled = True  # Settings enables it

        with patch("nous.infrastructure.voice.factory.get_voice_engine") as mock_get_engine:
            mock_engine = AsyncMock()
            mock_engine.health_check.return_value = True
            mock_engine.synthesize.return_value = b"fake_wav_data"
            mock_get_engine.return_value = mock_engine
            mock_engine._voice = "default"

            from nous.api.mcp._tools_irodori import _tool_irodori_tts

            result = await _tool_irodori_tts(mock_ctx, "test", "こんにちは")
            data = json.loads(result)
            assert data["ok"] is True
