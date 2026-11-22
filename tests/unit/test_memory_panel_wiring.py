"""Memory panel wiring fixes: preliminary flag, saved-only SSE, keys, actions."""

from __future__ import annotations

import json

import pytest


class TestPreliminaryFlag:
    def test_sse_includes_preliminary(self):
        from nous.application.chat.events import MemoryActivitySSE

        sse = MemoryActivitySSE(retrieved=[{"content": "x"}], saved=[])
        assert hasattr(sse, "preliminary")
        payload = json.loads(sse.to_sse().split("data: ", 1)[1])
        assert payload["type"] == "memory_activity"
        assert payload["preliminary"] is False

        pre = MemoryActivitySSE(retrieved=[{"content": "x"}], saved=[], preliminary=True)
        payload2 = json.loads(pre.to_sse().split("data: ", 1)[1])
        assert payload2["preliminary"] is True

    def test_service_has_no_preliminary_sse(self):
        """速報（preliminary=True）は廃止。検索は PrepareStep の 1 回だけ。"""
        import inspect

        from nous.application.chat import service as svc

        src = inspect.getsource(svc.ChatService.chat)
        assert "preliminary=True" not in src
        assert "_search_keyword_fast" not in src


class TestSavedOnlyTracking:
    @pytest.mark.asyncio
    async def test_duplicate_fact_not_marked_saved(self):
        from unittest.mock import AsyncMock, MagicMock, patch

        from nous.application.chat.memory_extractor import run_memory_llm
        from nous.domain.shared.result import Success

        ctx = MagicMock()
        ctx.persona = "test_persona"
        ctx.persona_service = MagicMock()
        state = MagicMock()
        state.user_info = {}
        state.emotion = ""
        state.mental_state = ""
        state.physical_state = ""
        state.environment = ""
        state.fatigue = None
        state.warmth = None
        state.arousal = None
        ctx.persona_service.get_context.return_value = Success(state)
        ctx.memory_service = MagicMock()
        ctx.memory_service.create_memory = AsyncMock()
        ctx.memory_service.get_by_tags.return_value = Success([])
        ctx.equipment_service = MagicMock()
        ctx.equipment_service.get_equipment.return_value = Success({})
        ctx.equipment_service.search_items.return_value = Success([])
        # dup hit score 0.99 → skip
        hit = MagicMock()
        hit.score = 0.99
        ctx.search_engine = MagicMock()
        ctx.search_engine.search = AsyncMock(return_value=Success([hit]))
        ctx.vector_store = None

        config = MagicMock()
        config.extract_model = "m"
        config.get_effective_api_key.return_value = "k"
        config.get_effective_model.return_value = "m"
        config.get_effective_base_url.return_value = ""
        config.provider = "openai"
        config.system_prompt = ""

        llm_result = {
            "facts": [{"content": "dup fact", "tags": ["auto_extract"]}],
            "context_update": {},
            "inventory_update": {},
        }
        with patch("nous.application.chat.memory_llm.MemoryLLM") as mock_llm:
            mock_llm.return_value.process = AsyncMock(return_value=llm_result)
            result = await run_memory_llm(ctx, config, {"user": "u", "assistant": "a"})

        assert result["facts"][0].get("_saved") is False
        ctx.memory_service.create_memory.assert_not_called()

    @pytest.mark.asyncio
    async def test_saved_fact_gets_key(self):
        from unittest.mock import AsyncMock, MagicMock, patch

        from nous.application.chat.memory_extractor import run_memory_llm
        from nous.domain.shared.result import Success

        ctx = MagicMock()
        ctx.persona = "test_persona"
        ctx.persona_service = MagicMock()
        state = MagicMock()
        state.user_info = {}
        state.emotion = ""
        state.mental_state = ""
        state.physical_state = ""
        state.environment = ""
        state.fatigue = None
        state.warmth = None
        state.arousal = None
        ctx.persona_service.get_context.return_value = Success(state)
        ctx.memory_service = MagicMock()
        mem = MagicMock()
        mem.key = "mem_123"
        mem.content = "new fact"
        ctx.memory_service.create_memory = AsyncMock(return_value=Success(mem))
        ctx.memory_service.get_by_tags.return_value = Success([])
        ctx.equipment_service = MagicMock()
        ctx.equipment_service.get_equipment.return_value = Success({})
        ctx.equipment_service.search_items.return_value = Success([])
        ctx.search_engine = MagicMock()
        ctx.search_engine.search = AsyncMock(return_value=Success([]))
        ctx.vector_store = None

        config = MagicMock()
        config.extract_model = "m"
        config.get_effective_api_key.return_value = "k"
        config.get_effective_model.return_value = "m"
        config.get_effective_base_url.return_value = ""
        config.provider = "openai"
        config.system_prompt = ""

        llm_result = {
            "facts": [{"content": "new fact", "tags": ["auto_extract"]}],
            "context_update": {},
            "inventory_update": {},
        }
        with patch("nous.application.chat.memory_llm.MemoryLLM") as mock_llm:
            mock_llm.return_value.process = AsyncMock(return_value=llm_result)
            result = await run_memory_llm(ctx, config, {"user": "u", "assistant": "a"})

        assert result["facts"][0].get("_saved") is True
        assert result["facts"][0].get("memory_key") == "mem_123"


class TestPostBuildsSavedOnlySSE:
    def test_post_source_filters_unsaved(self):
        import inspect

        from nous.application.chat.pipeline import post as post_mod

        src = inspect.getsource(post_mod.PostProcessStep.run)
        assert "_saved" in src
        assert "memory_key" in src or '"key"' in src
