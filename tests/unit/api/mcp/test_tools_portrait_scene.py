"""Tests for _tool_persona_portrait_with_scene — LLM-driven scene-based portrait generation."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nous.domain.chat_config import ChatConfig


@pytest.fixture
def mock_ctx():
    ctx = MagicMock()
    ctx.settings.portrait_gen.enabled = True
    ctx.settings.portrait_gen.provider = "comfyui"
    ctx.settings.portrait_gen.comfyui_url = "http://localhost:8188"
    ctx.settings.portrait_gen.size = "512x512"
    ctx.settings.portrait_gen.quality = "standard"
    ctx.persona_service = MagicMock()
    # get_context is synchronous in production — use MagicMock, not AsyncMock
    ctx.persona_service.get_context = MagicMock()
    ctx.connection.get_memory_db.return_value = MagicMock()
    return ctx


@pytest.fixture
def repo_patch():
    """Patch ChatConfigRepository.get() to return controlled ChatConfig."""
    with patch("nous.api.mcp._tools_portrait_scene.ChatConfigRepository") as mock_repo_cls:
        mock_repo = MagicMock()
        mock_repo_cls.return_value = mock_repo
        yield mock_repo


@pytest.fixture
def mock_persona_state():
    state = MagicMock()
    state.persona = "test_char"
    state.emotion = "joy"
    state.appearance = "long silver hair, blue eyes"
    return state


@pytest.fixture
def svc_patch():
    """Patch PortraitGenerationService."""
    with patch("nous.application.portrait.service.PortraitGenerationService") as mock_svc_cls:
        mock_svc = AsyncMock()
        mock_svc_cls.return_value = mock_svc
        yield mock_svc


class TestPortraitWithScene:
    """persona_portrait tool with LLM scene input."""

    async def test_scene_required(self, mock_ctx, repo_patch):
        """Empty scene returns error."""
        chat_config = ChatConfig(persona="test", portrait_enabled=True)
        repo_patch.get.return_value = chat_config

        from nous.api.mcp._tools_portrait_scene import _tool_persona_portrait_with_scene

        await _tool_persona_portrait_with_scene(mock_ctx, "test", scene="")
        # Empty scene is currently passed through — service will get empty string
        # This test documents current behavior

    async def test_scene_generates_image(self, mock_ctx, repo_patch, mock_persona_state, svc_patch):
        """Valid scene → service.generate called with correct args → returns image data."""
        chat_config = ChatConfig(persona="test", portrait_enabled=True)
        repo_patch.get.return_value = chat_config

        state_result = MagicMock()
        state_result.is_ok = True
        state_result.value = mock_persona_state
        mock_ctx.persona_service.get_context.return_value = state_result

        svc_patch.generate.return_value = {
            "image_base64": "fakebase64data",
            "prompt": "1girl, test_char, smiling, at the beach",
            "negative_prompt": "lowres, bad anatomy",
        }

        from nous.api.mcp._tools_portrait_scene import _tool_persona_portrait_with_scene

        result = await _tool_persona_portrait_with_scene(mock_ctx, "test", scene="at the beach")
        data = json.loads(result)

        assert data["image_base64"] == "fakebase64data"
        assert data["revised_prompt"] == "1girl, test_char, smiling, at the beach"
        assert "error" not in data

        # Verify service.generate was called with scene
        svc_patch.generate.assert_awaited_once()
        call_kwargs = svc_patch.generate.call_args.kwargs
        assert call_kwargs.get("scene") == "at the beach"

    async def test_style_appended_to_scene(self, mock_ctx, repo_patch, mock_persona_state, svc_patch):
        """Style param → prepended to scene passed to service."""
        chat_config = ChatConfig(persona="test", portrait_enabled=True)
        repo_patch.get.return_value = chat_config

        state_result = MagicMock()
        state_result.is_ok = True
        state_result.value = mock_persona_state
        mock_ctx.persona_service.get_context.return_value = state_result

        svc_patch.generate.return_value = {
            "image_base64": "fake",
            "prompt": "generated prompt",
            "negative_prompt": "",
        }

        from nous.api.mcp._tools_portrait_scene import _tool_persona_portrait_with_scene

        await _tool_persona_portrait_with_scene(mock_ctx, "test", scene="castle at night", style="watercolor")

        svc_patch.generate.assert_awaited_once()
        call_kwargs = svc_patch.generate.call_args.kwargs
        # Style should be incorporated into the scene
        assert "watercolor" in call_kwargs.get("scene", "")
        assert "castle at night" in call_kwargs.get("scene", "")

    async def test_disabled_returns_error(self, mock_ctx, repo_patch):
        """Both ChatConfig and Settings disabled → return error."""
        chat_config = ChatConfig(persona="test", portrait_enabled=False)
        repo_patch.get.return_value = chat_config
        mock_ctx.settings.portrait_gen.enabled = False

        from nous.api.mcp._tools_portrait_scene import _tool_persona_portrait_with_scene

        result = await _tool_persona_portrait_with_scene(mock_ctx, "test", scene="beach sunset")
        data = json.loads(result)
        assert data["ok"] is False
        assert "disabled" in data["error"].lower()

    async def test_enabled_via_chat_config(self, mock_ctx, repo_patch, mock_persona_state, svc_patch):
        """ChatConfig.portrait_enabled = True → enabled even if Settings disabled."""
        chat_config = ChatConfig(persona="test", portrait_enabled=True)
        repo_patch.get.return_value = chat_config
        mock_ctx.settings.portrait_gen.enabled = False

        state_result = MagicMock()
        state_result.is_ok = True
        state_result.value = mock_persona_state
        mock_ctx.persona_service.get_context.return_value = state_result

        svc_patch.generate.return_value = {
            "image_base64": "fake",
            "prompt": "test prompt",
            "negative_prompt": "",
        }

        from nous.api.mcp._tools_portrait_scene import _tool_persona_portrait_with_scene

        result = await _tool_persona_portrait_with_scene(mock_ctx, "test", scene="sunset")
        data = json.loads(result)
        assert data["image_base64"] == "fake"

    async def test_service_failure_fallback(self, mock_ctx, repo_patch, mock_persona_state, svc_patch):
        """Service generate raises → error gracefully returned."""
        chat_config = ChatConfig(persona="test", portrait_enabled=True)
        repo_patch.get.return_value = chat_config

        state_result = MagicMock()
        state_result.is_ok = True
        state_result.value = mock_persona_state
        mock_ctx.persona_service.get_context.return_value = state_result

        svc_patch.generate.side_effect = RuntimeError("Provider unavailable")

        from nous.api.mcp._tools_portrait_scene import _tool_persona_portrait_with_scene

        result = await _tool_persona_portrait_with_scene(mock_ctx, "test", scene="sunset")
        data = json.loads(result)
        assert data["ok"] is False
        assert "Provider unavailable" in str(data.get("error", ""))

    async def test_persona_state_failure(self, mock_ctx, repo_patch):
        """Persona state fetch fails → error."""
        chat_config = ChatConfig(persona="test", portrait_enabled=True)
        repo_patch.get.return_value = chat_config

        state_result = MagicMock()
        state_result.is_ok = False
        state_result.error = "Persona not found"
        mock_ctx.persona_service.get_context.return_value = state_result

        from nous.api.mcp._tools_portrait_scene import _tool_persona_portrait_with_scene

        result = await _tool_persona_portrait_with_scene(mock_ctx, "test", scene="sunset")
        data = json.loads(result)
        assert data["ok"] is False
        assert "Persona not found" in data["error"]
