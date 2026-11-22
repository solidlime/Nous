"""Tests for builtin.py tool handler parameter validation."""

from __future__ import annotations

import json
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


# ---------------------------------------------------------------------------
# _handle_mcp_dispatch: envelope unwrap (card #72)
# ---------------------------------------------------------------------------


class TestMcpDispatchEnvelope:
    """chain: _tool_memory_search は {"ok","data","error"} envelope を返す。dispatcher が
    data を開かずトップレベルだけ見ていたため、chat からの memory_search が常に
    {"status":"ok"} に潰れていた（kanban #72）。"""

    async def test_memory_search_keeps_memories(self):
        from unittest.mock import patch

        from nous.application.chat.tools import builtin

        envelope = json.dumps({"ok": True, "data": {"memories": [{"key": "k1"}], "total_count": 1}, "error": None})
        with patch.dict(builtin.TOOL_DISPATCH, {"memory_search": AsyncMock(return_value=envelope)}):
            out = await builtin._handle_mcp_dispatch("memory_search", MagicMock(), MagicMock(), {"query": "x"})

        assert out["status"] == "ok"
        assert out["memories"] == [{"key": "k1"}]

    async def test_memory_create_keeps_key(self):
        from unittest.mock import patch

        from nous.application.chat.tools import builtin

        envelope = json.dumps({"ok": True, "data": {"key": "k2"}, "error": None})
        with patch.dict(builtin.TOOL_DISPATCH, {"memory_create": AsyncMock(return_value=envelope)}):
            out = await builtin._handle_mcp_dispatch("memory_create", MagicMock(), MagicMock(), {"content": "x"})

        assert out == {"status": "ok", "key": "k2"}

    async def test_legacy_dict_still_works(self):
        from unittest.mock import patch

        from nous.application.chat.tools import builtin

        with patch.dict(builtin.TOOL_DISPATCH, {"memory_read": AsyncMock(return_value={"ok": True, "result": "done"})}):
            out = await builtin._handle_mcp_dispatch("memory_read", MagicMock(), MagicMock(), {})

        assert out == {"result": "done"}

    async def test_envelope_error_message_is_string(self):
        from unittest.mock import patch

        from nous.application.chat.tools import builtin

        envelope = json.dumps({"ok": False, "data": None, "error": {"code": "NOT_FOUND", "message": "No memory"}})
        with patch.dict(builtin.TOOL_DISPATCH, {"memory_read": AsyncMock(return_value=envelope)}):
            out = await builtin._handle_mcp_dispatch("memory_read", MagicMock(), MagicMock(), {})

        assert out == {"status": "error", "message": "No memory"}

    async def test_legacy_exception_error_is_stringified(self):
        """旧 dict 契約は error に例外インスタンスを入れてくる（JSON 化不能）。"""
        from unittest.mock import patch

        from nous.application.chat.tools import builtin

        legacy = {"ok": False, "error": ValueError("boom")}
        with patch.dict(builtin.TOOL_DISPATCH, {"memory_read": AsyncMock(return_value=legacy)}):
            out = await builtin._handle_mcp_dispatch("memory_read", MagicMock(), MagicMock(), {})

        assert out["status"] == "error"
        assert out["message"] == "boom"
        json.dumps(out)  # 直列化できること

    async def test_none_error_falls_back_to_unknown(self):
        from unittest.mock import patch

        from nous.application.chat.tools import builtin

        with patch.dict(builtin.TOOL_DISPATCH, {"memory_read": AsyncMock(return_value={"ok": False, "error": None})}):
            out = await builtin._handle_mcp_dispatch("memory_read", MagicMock(), MagicMock(), {})

        assert out["message"] == "unknown"
