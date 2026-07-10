"""Tests for memory_llm.py — LLM-based memory extraction and context housekeeping."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nous.application.chat.memory_llm import (
    _HOUSEKEEPING_PROMPT,
    _MEMORY_LLM_PROMPT,
    _build_memory_llm_context,
    _parse_memory_llm_result,
    run_context_housekeeping,
    run_memory_llm,
)
from nous.domain.shared.result import Failure, Success

# ===========================================================================
# _parse_memory_llm_result()
# ===========================================================================


class TestParseMemoryLLMResult:
    """0.1: _parse_memory_llm_result() — LLM JSON response parser."""

    # -- Normal cases -------------------------------------------------------

    def test_parse_valid_full_json(self):
        """facts, goals, context_update, inventory_update all fields present."""
        raw = """{
            "facts": [
                {"content": "ユーザーは猫が好き", "importance": 0.8, "tags": ["preference"], "emotion": "joy"}
            ],
            "goals": [
                {"action": "create", "content": "新しいスキルを習得する"}
            ],
            "promises": [],
            "context_update": {
                "emotion": "joy",
                "emotion_intensity": 0.8,
                "mental_state": "リラックス",
                "physical_state": "元気",
                "environment": "自宅"
            },
            "inventory_update": {
                "equip": {"top": "白いシャツ"},
                "unequip": [],
                "add_items": [],
                "remove_items": [],
                "update_items": []
            }
        }"""
        result = _parse_memory_llm_result(raw)
        assert len(result["facts"]) == 1
        assert result["facts"][0]["content"] == "ユーザーは猫が好き"
        assert len(result["goals"]) == 1
        assert result["goals"][0]["content"] == "新しいスキルを習得する"
        assert result["goals"][0]["action"] == "create"
        assert result["promises"] == []
        assert result["context_update"]["emotion"] == "joy"
        assert result["inventory_update"]["equip"]["top"] == "白いシャツ"

    def test_parse_json_with_facts_only(self):
        """facts only, others empty."""
        raw = '{"facts": [{"content": "テスト事実", "importance": 0.5}]}'
        result = _parse_memory_llm_result(raw)
        assert len(result["facts"]) == 1
        assert result["facts"][0]["content"] == "テスト事実"
        assert result["goals"] == []
        assert result["promises"] == []
        assert result["context_update"] == {}
        assert result["inventory_update"] == {}

    def test_parse_json_with_goals_only(self):
        """goals only."""
        raw = '{"goals": [{"action": "create", "content": "毎日勉強する"}]}'
        result = _parse_memory_llm_result(raw)
        assert result["facts"] == []
        assert len(result["goals"]) == 1
        assert result["goals"][0]["content"] == "毎日勉強する"
        assert result["promises"] == []

    def test_parse_empty_dict(self):
        """empty {} — all fields default."""
        result = _parse_memory_llm_result("{}")
        assert result["facts"] == []
        assert result["goals"] == []
        assert result["promises"] == []
        assert result["context_update"] == {}
        assert result["inventory_update"] == {}

    def test_parse_markdown_codeblock(self):
        """JSON wrapped in ```json ... ```."""
        raw = """```json
{
    "facts": [
        {"content": "コードブロック内の事実", "importance": 0.6}
    ],
    "goals": [],
    "promises": [],
    "context_update": {},
    "inventory_update": {}
}
```"""
        result = _parse_memory_llm_result(raw)
        assert len(result["facts"]) == 1
        assert result["facts"][0]["content"] == "コードブロック内の事実"

    def test_parse_markdown_codeblock_without_lang(self):
        """JSON wrapped in ``` ... ``` (no language tag)."""
        raw = """```
{"facts": [{"content": "言語指定なし", "importance": 0.5}]}
```"""
        result = _parse_memory_llm_result(raw)
        assert len(result["facts"]) == 1
        assert result["facts"][0]["content"] == "言語指定なし"

    def test_parse_list_format_compat(self):
        """Backward compat: old list-format output."""
        raw = '[{"content": "古い形式の事実1", "importance": 0.7}, {"content": "古い形式の事実2"}]'
        result = _parse_memory_llm_result(raw)
        assert len(result["facts"]) == 2
        assert result["goals"] == []
        assert result["promises"] == []
        assert result["context_update"] == {}
        assert result["inventory_update"] == {}

    def test_parse_goals_with_fulfill_action(self):
        """action: 'fulfill' on a promise (old promise format)."""
        raw = """{
            "facts": [],
            "goals": [],
            "promises": [
                {"action": "fulfill", "memory_key": "prom_001", "content": "本を返す"}
            ],
            "context_update": {},
            "inventory_update": {}
        }"""
        result = _parse_memory_llm_result(raw)
        assert len(result["promises"]) == 1
        assert result["promises"][0]["action"] == "fulfill"
        assert result["promises"][0]["memory_key"] == "prom_001"

    def test_parse_goals_with_scope(self):
        """scope: 'self' | 'interpersonal' (extra fields preserved)."""
        raw = """{
            "facts": [],
            "goals": [
                {"action": "create", "content": "自分で勉強する", "scope": "self"},
                {"action": "create", "content": "友達と約束する", "scope": "interpersonal"}
            ],
            "promises": []
        }"""
        result = _parse_memory_llm_result(raw)
        assert len(result["goals"]) == 2
        assert result["goals"][0]["scope"] == "self"
        assert result["goals"][1]["scope"] == "interpersonal"

    # -- Error / edge cases -------------------------------------------------

    def test_parse_invalid_json(self):
        """Malformed JSON → empty result."""
        result = _parse_memory_llm_result("{broken json...")
        assert result == {}

    def test_parse_empty_string(self):
        """Empty string -> empty result."""
        result = _parse_memory_llm_result("")
        assert result == {}

    def test_parse_whitespace_only(self):
        """Whitespace only → empty result."""
        result = _parse_memory_llm_result("   \n  \t  ")
        assert result == {}

    def test_parse_none_input(self):
        """None input raises AttributeError (not handled by current code)."""
        with pytest.raises(AttributeError):
            _parse_memory_llm_result(None)  # type: ignore[arg-type]

    def test_parse_missing_required_fields(self):
        """facts key missing → default values."""
        raw = '{"goals": [{"action": "create", "content": "only goals"}]}'
        result = _parse_memory_llm_result(raw)
        assert result["facts"] == []
        assert len(result["goals"]) == 1
        assert result["context_update"] == {}
        assert result["inventory_update"] == {}

    def test_parse_extra_fields_ignored(self):
        """Unknown keys preserved but don't break known field parsing."""
        raw = """{
            "facts": [{"content": "known fact"}],
            "unknown_field": "should be ignored",
            "another_unknown": {"nested": "data"}
        }"""
        result = _parse_memory_llm_result(raw)
        assert len(result["facts"]) == 1
        assert result["facts"][0]["content"] == "known fact"
        # Extra fields are preserved by the parser (not stripped)
        assert "unknown_field" in result
        assert result["unknown_field"] == "should be ignored"

    def test_parse_nested_text_markdown(self):
        """Backtick in description text doesn't confuse parser."""
        raw = """{
            "facts": [
                {"content": "ユーザーは `code` が好きと言った", "importance": 0.5}
            ],
            "goals": [],
            "promises": [],
            "context_update": {},
            "inventory_update": {}
        }"""
        result = _parse_memory_llm_result(raw)
        assert len(result["facts"]) == 1
        assert "`code`" in result["facts"][0]["content"]

    def test_parse_fact_without_content_filtered(self):
        """Fact dict without 'content' key should be filtered out."""
        raw = '{"facts": [{"importance": 0.5}, {"content": "valid fact"}]}'
        result = _parse_memory_llm_result(raw)
        assert len(result["facts"]) == 1
        assert result["facts"][0]["content"] == "valid fact"

    def test_parse_non_dict_in_array_filtered(self):
        """Non-dict items in facts array should be filtered out."""
        raw = '{"facts": ["string_item", 42, {"content": "valid fact"}]}'
        result = _parse_memory_llm_result(raw)
        assert len(result["facts"]) == 1
        assert result["facts"][0]["content"] == "valid fact"

    def test_parse_goals_non_dict_filtered(self):
        """Non-dict items in goals filtered."""
        raw = '{"goals": ["bad", 123, {"action": "create", "content": "good goal"}]}'
        result = _parse_memory_llm_result(raw)
        assert len(result["goals"]) == 1
        assert result["goals"][0]["content"] == "good goal"

    def test_parse_list_with_non_dict_items(self):
        """Old list format: non-dict items filtered."""
        raw = '["string", 42, {"content": "valid"}]'
        result = _parse_memory_llm_result(raw)
        assert len(result["facts"]) == 1
        assert result["facts"][0]["content"] == "valid"

    def test_parse_extra_whitespace_in_json(self):
        """JSON with extra whitespace/newlines still parses."""
        raw = """{
            "facts": [{"content": "trimmed fact"}]



        }"""
        result = _parse_memory_llm_result(raw)
        assert len(result["facts"]) == 1


# ===========================================================================
# _MEMORY_LLM_PROMPT format tests
# ===========================================================================


class TestMemoryLLMPromptFormat:
    """0.3: _MEMORY_LLM_PROMPT format string tests."""

    def test_prompt_format_all_placeholders(self):
        """All placeholders (persona_name, user_name, persona_gender, etc.) filled."""
        formatted = _MEMORY_LLM_PROMPT.format(
            persona_name="テストペルソナ",
            persona_identity="あなたはテストペルソナです。",
            context="ユーザー名: テストユーザー",
            commitments="[goal] key=mem_001: 目標内容",
            inventory="  - アイテムA\n  - アイテムB",
            user_message="こんにちは",
            assistant_response="はい、こんにちは",
        )
        assert "テストペルソナ" in formatted
        assert "テストユーザー" in formatted
        assert "目標内容" in formatted
        assert "アイテムA" in formatted
        assert "こんにちは" in formatted

    def test_prompt_format_partial_info(self):
        """Some fields empty/not set — should still format correctly."""
        formatted = _MEMORY_LLM_PROMPT.format(
            persona_name="",
            persona_identity="",
            context="",
            commitments="",
            inventory="",
            user_message="hello",
            assistant_response="world",
        )
        # Should still produce a valid string with "hello" and "world"
        assert "hello" in formatted
        assert "world" in formatted
        # '[assistant' is part of the template literal, not the persona_name placeholder
        assert "[assistant" in formatted

    def test_prompt_no_format_errors(self):
        """All required keys present — no KeyError."""
        kwargs = {
            "persona_name": "assistant",
            "persona_identity": "あなたは assistant として振る舞います。",
            "context": "(情報なし)",
            "commitments": "(なし)",
            "inventory": "(なし)",
            "user_message": "test",
            "assistant_response": "response",
        }
        formatted = _MEMORY_LLM_PROMPT.format(**kwargs)
        assert "assistant" in formatted
        assert "test" in formatted
        assert "response" in formatted

    def test_prompt_contains_required_sections(self):
        """Check that key sections exist in the prompt."""
        formatted = _MEMORY_LLM_PROMPT.format(
            persona_name="助手",
            persona_identity="あなたは助手です。",
            context="何もなし",
            commitments="何もなし",
            inventory="何もなし",
            user_message="msg",
            assistant_response="resp",
        )
        assert "facts" in formatted
        assert "goals" in formatted
        assert "promises" in formatted
        assert "context_update" in formatted
        assert "inventory_update" in formatted
        assert "【出力形式】" in formatted
        assert "【注意】" in formatted

    def test_prompt_placeholder_consistency(self):
        """All {placeholders} in template match expected keys."""
        import re

        placeholders = set(re.findall(r"\{(\w+)\}", _MEMORY_LLM_PROMPT))
        expected = {
            "persona_name",
            "persona_identity",
            "context",
            "commitments",
            "inventory",
            "user_message",
            "assistant_response",
        }
        assert placeholders == expected, f"Unexpected placeholders: {placeholders - expected}"


# ===========================================================================
# _HOUSEKEEPING_PROMPT format tests
# ===========================================================================


class TestHousekeepingPromptFormat:
    """_HOUSEKEEPING_PROMPT format string tests."""

    def test_housekeeping_prompt_format(self):
        """All placeholders fill correctly."""
        formatted = _HOUSEKEEPING_PROMPT.format(
            persona_name="test_persona",
            goals="  - key=goal_001: 朝活する",
            promises="  - key=prom_001: 本を読む",
            inventory="  - アイテムX",
        )
        assert "test_persona" in formatted
        assert "goal_001" in formatted
        assert "prom_001" in formatted
        assert "アイテムX" in formatted

    def test_housekeeping_prompt_placeholders(self):
        """All {placeholders} match expected keys."""
        import re

        placeholders = set(re.findall(r"\{(\w+)\}", _HOUSEKEEPING_PROMPT))
        expected = {"persona_name", "goals", "promises", "inventory"}
        assert placeholders == expected


# ===========================================================================
# _build_memory_llm_context()
# ===========================================================================


class TestBuildMemoryLLMContext:
    """0.2: _build_memory_llm_context() — context builder tests."""

    @pytest.fixture
    def mock_ctx(self):
        ctx = MagicMock()
        ctx.persona = "test_persona"
        ctx.persona_service = MagicMock()
        ctx.memory_service = MagicMock()
        ctx.equipment_service = MagicMock()
        ctx.search_engine = MagicMock()
        return ctx

    @pytest.mark.asyncio
    async def test_context_empty(self, mock_ctx):
        """Empty commitments + empty equipment."""
        # persona_service.get_context → state with no user_info, emotion etc
        state = MagicMock()
        state.user_info = {}
        state.emotion = ""
        state.mental_state = ""
        state.physical_state = ""
        state.environment = ""
        mock_ctx.persona_service.get_context.return_value = Success(state)

        # memory_service.get_by_tags → empty for both goal and promise
        mock_ctx.memory_service.get_by_tags.return_value = Success([])

        # equipment_service.get_equipment → empty
        mock_ctx.equipment_service.get_equipment.return_value = Success({})

        # equipment_service.search_items → empty
        mock_ctx.equipment_service.search_items.return_value = Success([])

        context_str, commitments_str, inventory_str = await _build_memory_llm_context(mock_ctx)

        assert context_str == ""
        assert commitments_str == ""
        assert inventory_str == ""

    @pytest.mark.asyncio
    async def test_context_goals_only(self, mock_ctx):
        """Goals only."""
        state = MagicMock()
        state.user_info = {"name": "テストユーザー"}
        state.emotion = "joy"
        state.emotion_intensity = 0.8
        state.mental_state = "集中"
        state.physical_state = ""
        state.environment = "カフェ"
        mock_ctx.persona_service.get_context.return_value = Success(state)

        # Return goals for first call (["goal", "active"]), empty for promises
        goal_mem = MagicMock()
        goal_mem.key = "goal_001"
        goal_mem.content = "毎日ランニングする"
        goal_mem.id = None

        def get_by_tags_side_effect(tags):
            if tags == ["goal", "active"]:
                return Success([goal_mem])
            return Success([])

        mock_ctx.memory_service.get_by_tags.side_effect = get_by_tags_side_effect

        mock_ctx.equipment_service.get_equipment.return_value = Success({})
        mock_ctx.equipment_service.search_items.return_value = Success([])

        context_str, commitments_str, inventory_str = await _build_memory_llm_context(mock_ctx)

        assert "テストユーザー" in context_str
        assert "joy" in context_str
        assert "goal_001" in commitments_str
        assert "毎日ランニングする" in commitments_str

    @pytest.mark.asyncio
    async def test_context_promises_only(self, mock_ctx):
        """Interpersonal goals only (scope='interpersonal')."""
        state = MagicMock()
        state.user_info = {}
        state.emotion = ""
        state.mental_state = ""
        state.physical_state = ""
        state.environment = ""
        mock_ctx.persona_service.get_context.return_value = Success(state)

        ip_mem = MagicMock()
        ip_mem.key = "ip_001"
        ip_mem.content = "明日までに本を返す"
        ip_mem.id = None

        def get_by_tags_side_effect(tags):
            if tags == ["goal", "active", "interpersonal"]:
                return Success([ip_mem])
            return Success([])

        mock_ctx.memory_service.get_by_tags.side_effect = get_by_tags_side_effect
        mock_ctx.equipment_service.get_equipment.return_value = Success({})
        mock_ctx.equipment_service.search_items.return_value = Success([])

        context_str, commitments_str, inventory_str = await _build_memory_llm_context(mock_ctx)

        assert context_str == ""
        assert "ip_001" in commitments_str
        assert "明日までに本を返す" in commitments_str

    @pytest.mark.asyncio
    async def test_context_mixed(self, mock_ctx):
        """Self goals + interpersonal goals mixed."""
        state = MagicMock()
        state.user_info = {"name": "ユーザーA"}
        state.emotion = "neutral"
        state.emotion_intensity = None
        state.mental_state = ""
        state.physical_state = ""
        state.environment = ""
        mock_ctx.persona_service.get_context.return_value = Success(state)

        goal_mem = MagicMock()
        goal_mem.key = "goal_001"
        goal_mem.content = "毎日勉強"
        goal_mem.id = None

        ip_mem = MagicMock()
        ip_mem.key = "ip_001"
        ip_mem.content = "約束を守る"
        ip_mem.id = None

        def get_by_tags_side_effect(tags):
            if tags == ["goal", "active"]:
                return Success([goal_mem])
            elif tags == ["goal", "active", "interpersonal"]:
                return Success([ip_mem])
            return Success([])

        mock_ctx.memory_service.get_by_tags.side_effect = get_by_tags_side_effect
        mock_ctx.equipment_service.get_equipment.return_value = Success({})
        mock_ctx.equipment_service.search_items.return_value = Success([])

        context_str, commitments_str, inventory_str = await _build_memory_llm_context(mock_ctx)

        assert "ユーザーA" in context_str
        assert "goal_001" in commitments_str
        assert "ip_001" in commitments_str

    @pytest.mark.asyncio
    async def test_context_with_equipment(self, mock_ctx):
        """With equipment items."""
        state = MagicMock()
        state.user_info = {}
        state.emotion = ""
        state.mental_state = ""
        state.physical_state = ""
        state.environment = ""
        mock_ctx.persona_service.get_context.return_value = Success(state)
        mock_ctx.memory_service.get_by_tags.return_value = Success([])

        # Equipment with items
        mock_ctx.equipment_service.get_equipment.return_value = Success(
            {
                "top": "白いシャツ",
                "bottom": "青いジーンズ",
            }
        )

        # Inventory items
        item = MagicMock()
        item.name = "ラッキーコイン"
        item.description = "銀色のコイン"
        mock_ctx.equipment_service.search_items.return_value = Success([item])

        context_str, commitments_str, inventory_str = await _build_memory_llm_context(mock_ctx)

        assert "白いシャツ" in context_str
        assert "青いジーンズ" in context_str
        assert "ラッキーコイン" in inventory_str

    @pytest.mark.asyncio
    async def test_context_with_long_commitments(self, mock_ctx):
        """10+ goal/interpersonal entries."""
        state = MagicMock()
        state.user_info = {}
        state.emotion = ""
        state.mental_state = ""
        state.physical_state = ""
        state.environment = ""
        mock_ctx.persona_service.get_context.return_value = Success(state)

        # 5 self goals max
        goals = []
        for i in range(5):
            g = MagicMock()
            g.key = f"goal_{i:03d}"
            g.content = f"目標{i + 1}: テスト"
            g.id = None
            goals.append(g)

        # 5 interpersonal goals max
        ip_goals = []
        for i in range(5):
            p = MagicMock()
            p.key = f"ip_{i:03d}"
            p.content = f"約束{i + 1}: テスト"
            p.id = None
            ip_goals.append(p)

        def get_by_tags_side_effect(tags):
            if tags == ["goal", "active"]:
                return Success(goals)
            elif tags == ["goal", "active", "interpersonal"]:
                return Success(ip_goals)
            return Success([])

        mock_ctx.memory_service.get_by_tags.side_effect = get_by_tags_side_effect
        mock_ctx.equipment_service.get_equipment.return_value = Success({})
        mock_ctx.equipment_service.search_items.return_value = Success([])

        context_str, commitments_str, inventory_str = await _build_memory_llm_context(mock_ctx)

        # Commitments should contain all 10 entries
        assert "goal_000" in commitments_str
        assert "goal_004" in commitments_str
        assert "ip_000" in commitments_str
        assert "ip_004" in commitments_str
        assert context_str == ""
        assert inventory_str == ""

    @pytest.mark.asyncio
    async def test_context_uses_id_fallback(self, mock_ctx):
        """When key is None, uses 'id' as fallback."""
        state = MagicMock()
        state.user_info = {}
        state.emotion = ""
        state.mental_state = ""
        state.physical_state = ""
        state.environment = ""
        mock_ctx.persona_service.get_context.return_value = Success(state)

        mem = MagicMock()
        mem.key = None
        mem.id = "mem_id_123"
        mem.content = "content here"

        def get_by_tags_side_effect(tags):
            if tags == ["goal", "active"]:
                return Success([mem])
            return Success([])

        mock_ctx.memory_service.get_by_tags.side_effect = get_by_tags_side_effect
        mock_ctx.equipment_service.get_equipment.return_value = Success({})
        mock_ctx.equipment_service.search_items.return_value = Success([])

        context_str, commitments_str, inventory_str = await _build_memory_llm_context(mock_ctx)

        assert "mem_id_123" in commitments_str

    @pytest.mark.asyncio
    async def test_context_service_failure_graceful(self, mock_ctx):
        """Service failure returns empty rather than crashing."""
        mock_ctx.persona_service.get_context.return_value = Failure(Exception("db error"))
        mock_ctx.memory_service.get_by_tags.return_value = Failure(Exception("mem error"))
        mock_ctx.equipment_service.get_equipment.return_value = Failure(Exception("eq error"))
        mock_ctx.equipment_service.search_items.return_value = Failure(Exception("inv error"))

        context_str, commitments_str, inventory_str = await _build_memory_llm_context(mock_ctx)

        assert context_str == ""
        assert commitments_str == ""
        assert inventory_str == ""


# ===========================================================================
# run_context_housekeeping()
# ===========================================================================


class TestRunContextHousekeeping:
    """0.4: run_context_housekeeping() parse tests."""

    @pytest.fixture
    def mock_ctx(self):
        ctx = MagicMock()
        ctx.persona = "test_persona"
        ctx.memory_service = MagicMock()
        ctx.equipment_service = MagicMock()
        ctx.search_engine = MagicMock()
        return ctx

    @pytest.fixture
    def mock_config(self):
        config = MagicMock()
        config.extract_model = "gpt-4o-mini"
        config.get_effective_api_key.return_value = "sk-test"
        config.get_effective_model.return_value = "gpt-4o-mini"
        config.get_effective_base_url.return_value = "https://api.openai.com/v1"
        config.provider = "openai"
        return config

    @pytest.mark.asyncio
    async def test_housekeeping_valid_result(self, mock_ctx, mock_config):
        """Normal housekeeping result parsing."""
        mock_ctx.memory_service.get_by_tags.return_value = Success([])
        mock_ctx.equipment_service.search_items.return_value = Success([])

        # Mock the LLM stream to return valid JSON
        from nous.infrastructure.llm.base import DoneEvent, TextDeltaEvent

        async def mock_stream(**kwargs):
            yield TextDeltaEvent(
                content='{"cancel_goals":["goal_001"],"cancel_promises":["prom_001"],"remove_items":["古いアイテム"]}'
            )
            yield DoneEvent()

        with patch("nous.application.chat.memory_llm.get_provider") as mock_get_provider:
            mock_provider = AsyncMock()
            mock_provider.stream = mock_stream
            mock_get_provider.return_value = mock_provider

            # Mock the memory service updates
            mock_ctx.memory_service.update_memory.return_value = Success(None)
            mock_ctx.equipment_service.remove_item.return_value = Success(None)

            result = await run_context_housekeeping(mock_ctx, mock_config)

        assert result["cancelled_goals"] == ["goal_001"]
        assert result["cancelled_promises"] == ["prom_001"]
        assert result["removed_items"] == ["古いアイテム"]

    @pytest.mark.asyncio
    async def test_housekeeping_invalid_json(self, mock_ctx, mock_config):
        """Invalid JSON → empty lists returned."""
        mock_ctx.memory_service.get_by_tags.return_value = Success([])
        mock_ctx.equipment_service.search_items.return_value = Success([])

        from nous.infrastructure.llm.base import DoneEvent, TextDeltaEvent

        async def mock_stream(**kwargs):
            yield TextDeltaEvent(content="不正なJSON{{{")
            yield DoneEvent()

        with patch("nous.application.chat.memory_llm.get_provider") as mock_get_provider:
            mock_provider = AsyncMock()
            mock_provider.stream = mock_stream
            mock_get_provider.return_value = mock_provider

            result = await run_context_housekeeping(mock_ctx, mock_config)

        assert result["cancelled_goals"] == []
        assert result["cancelled_promises"] == []
        assert result["removed_items"] == []

    @pytest.mark.asyncio
    async def test_housekeeping_no_cancellations(self, mock_ctx, mock_config):
        """No cancellation targets — empty arrays."""
        mock_ctx.memory_service.get_by_tags.return_value = Success([])
        mock_ctx.equipment_service.search_items.return_value = Success([])

        from nous.infrastructure.llm.base import DoneEvent, TextDeltaEvent

        async def mock_stream(**kwargs):
            yield TextDeltaEvent(content='{"cancel_goals":[],"cancel_promises":[],"remove_items":[]}')
            yield DoneEvent()

        with patch("nous.application.chat.memory_llm.get_provider") as mock_get_provider:
            mock_provider = AsyncMock()
            mock_provider.stream = mock_stream
            mock_get_provider.return_value = mock_provider

            result = await run_context_housekeeping(mock_ctx, mock_config)

        assert result["cancelled_goals"] == []
        assert result["cancelled_promises"] == []
        assert result["removed_items"] == []

    @pytest.mark.asyncio
    async def test_housekeeping_llm_not_configured(self, mock_ctx, mock_config):
        """When API key or model is missing, returns skipped."""
        mock_config.get_effective_api_key.return_value = ""

        result = await run_context_housekeeping(mock_ctx, mock_config)
        assert result == {"skipped": "LLM not configured"}

    @pytest.mark.asyncio
    async def test_housekeeping_provider_init_failure(self, mock_ctx, mock_config):
        """Provider init failure returns error dict."""
        mock_ctx.memory_service.get_by_tags.return_value = Success([])
        mock_ctx.equipment_service.search_items.return_value = Success([])

        with patch("nous.application.chat.memory_llm.get_provider") as mock_get_provider:
            mock_get_provider.side_effect = ValueError("bad provider config")

            result = await run_context_housekeeping(mock_ctx, mock_config)

        assert "error" in result
        assert "bad provider config" in result["error"]

    @pytest.mark.asyncio
    async def test_housekeeping_markdown_codeblock(self, mock_ctx, mock_config):
        """JSON in markdown code block."""
        mock_ctx.memory_service.get_by_tags.return_value = Success([])
        mock_ctx.equipment_service.search_items.return_value = Success([])

        from nous.infrastructure.llm.base import DoneEvent, TextDeltaEvent

        async def mock_stream(**kwargs):
            yield TextDeltaEvent(
                content="""```json
{"cancel_goals":["goal_002"],"cancel_promises":[],"remove_items":[]}
```"""
            )
            yield DoneEvent()

        with patch("nous.application.chat.memory_llm.get_provider") as mock_get_provider:
            mock_provider = AsyncMock()
            mock_provider.stream = mock_stream
            mock_get_provider.return_value = mock_provider

            mock_ctx.memory_service.update_memory.return_value = Success(None)
            mock_ctx.equipment_service.remove_item.return_value = Success(None)

            result = await run_context_housekeeping(mock_ctx, mock_config)

        assert result["cancelled_goals"] == ["goal_002"]

    @pytest.mark.asyncio
    async def test_housekeeping_empty_string_keys_skipped(self, mock_ctx, mock_config):
        """Empty string keys in cancel lists are skipped."""
        mock_ctx.memory_service.get_by_tags.return_value = Success([])
        mock_ctx.equipment_service.search_items.return_value = Success([])

        from nous.infrastructure.llm.base import DoneEvent, TextDeltaEvent

        async def mock_stream(**kwargs):
            yield TextDeltaEvent(
                content='{"cancel_goals":["goal_001", "", "  "],"cancel_promises":[""],"remove_items":["", "valid_item"]}'
            )
            yield DoneEvent()

        with patch("nous.application.chat.memory_llm.get_provider") as mock_get_provider:
            mock_provider = AsyncMock()
            mock_provider.stream = mock_stream
            mock_get_provider.return_value = mock_provider

            mock_ctx.memory_service.update_memory.return_value = Success(None)
            mock_ctx.equipment_service.remove_item.return_value = Success(None)

            result = await run_context_housekeeping(mock_ctx, mock_config)

        assert result["cancelled_goals"] == ["goal_001"]
        assert result["cancelled_promises"] == []
        assert result["removed_items"] == ["valid_item"]

    @pytest.mark.asyncio
    async def test_housekeeping_update_memory_failure_skipped(self, mock_ctx, mock_config):
        """When update_memory fails, that key is not included in results."""
        mock_ctx.memory_service.get_by_tags.return_value = Success([])
        mock_ctx.equipment_service.search_items.return_value = Success([])

        from nous.infrastructure.llm.base import DoneEvent, TextDeltaEvent

        async def mock_stream(**kwargs):
            yield TextDeltaEvent(
                content='{"cancel_goals":["goal_001","goal_002"],"cancel_promises":[],"remove_items":[]}'
            )
            yield DoneEvent()

        with patch("nous.application.chat.memory_llm.get_provider") as mock_get_provider:
            mock_provider = AsyncMock()
            mock_provider.stream = mock_stream
            mock_get_provider.return_value = mock_provider

            # First call succeeds, second fails
            mock_ctx.memory_service.update_memory.side_effect = [
                Success(None),
                Failure(Exception("update failed")),
            ]

            result = await run_context_housekeeping(mock_ctx, mock_config)

        assert result["cancelled_goals"] == ["goal_001"]  # only the successful one
        assert mock_ctx.memory_service.update_memory.call_count == 2


# ===========================================================================
# run_memory_llm() — context_update automation
# ===========================================================================


class TestRunMemoryLLM:
    """0.5: run_memory_llm() context_update auto-apply tests."""

    @pytest.fixture
    def mock_ctx(self):
        ctx = MagicMock()
        ctx.persona = "test_persona"
        ctx.persona_service = MagicMock()
        ctx.memory_service = MagicMock()
        ctx.equipment_service = MagicMock()
        ctx.search_engine = MagicMock()

        # _build_memory_llm_context 用の state — 空値で emotion ブロックに入らないように
        state = MagicMock()
        state.user_info = {}
        state.emotion = ""
        state.mental_state = ""
        state.physical_state = ""
        state.environment = ""
        ctx.persona_service.get_context.return_value = Success(state)

        # 空のメモリ・装備・インベントリ
        ctx.memory_service.get_by_tags.return_value = Success([])
        ctx.equipment_service.get_equipment.return_value = Success({})
        ctx.equipment_service.search_items.return_value = Success([])

        # search_engine.search — 重複チェックはヒットしない（空）
        ctx.search_engine.search.return_value = Success([])

        return ctx

    @pytest.fixture
    def mock_config(self):
        config = MagicMock()
        config.extract_model = "gpt-4o-mini"
        config.get_effective_api_key.return_value = "sk-test"
        config.get_effective_model.return_value = "gpt-4o-mini"
        config.get_effective_base_url.return_value = "https://api.openai.com/v1"
        config.provider = "openai"
        config.system_prompt = ""
        return config

    @pytest.mark.asyncio
    async def test_housekeeping_applies_context_update(self, mock_ctx, mock_config):
        """LLM result with context_update → update_emotion / memory for mental_state / update_persona_info."""
        payload = {"user": "こんにちは", "assistant": "楽しいね！"}
        llm_result = {
            "facts": [],
            "goals": [],
            "promises": [],
            "context_update": {
                "emotion": "joy",
                "emotion_intensity": 0.85,
                "mental_state": "リラックス",
                "context_note": "会話は和やかだった",
            },
            "inventory_update": {},
        }

        with patch("nous.application.chat.memory_llm.MemoryLLM") as mock_llm:
            instance = mock_llm.return_value
            instance.process = AsyncMock(return_value=llm_result)

            await run_memory_llm(mock_ctx, mock_config, payload)

        mock_ctx.persona_service.update_emotion.assert_called_once_with(
            "test_persona",
            "joy",
            0.85,
            context="llm_suggested",
        )
        # mental_state → memory, not update_physical_state
        mock_ctx.memory_service.create_memory.assert_any_call(
            content="mental_state: リラックス",
            tags=["mental_state", "mind"],
            importance=0.6,
        )
        mock_ctx.persona_service.update_physical_state.assert_not_called()
        mock_ctx.persona_service.update_persona_info.assert_called_once_with(
            "test_persona",
            {"context_note": "会話は和やかだった"},
        )

    @pytest.mark.asyncio
    async def test_housekeeping_skips_empty_context_update(self, mock_ctx, mock_config):
        """Empty context_update dict → no update calls."""
        payload = {"user": "test", "assistant": "response"}
        llm_result = {
            "facts": [],
            "goals": [],
            "promises": [],
            "context_update": {},
            "inventory_update": {},
        }

        with patch("nous.application.chat.memory_llm.MemoryLLM") as mock_llm:
            instance = mock_llm.return_value
            instance.process = AsyncMock(return_value=llm_result)

            await run_memory_llm(mock_ctx, mock_config, payload)

        mock_ctx.persona_service.update_emotion.assert_not_called()
        mock_ctx.persona_service.update_physical_state.assert_not_called()
        mock_ctx.persona_service.update_persona_info.assert_not_called()

    @pytest.mark.asyncio
    async def test_context_update_emotion_only(self, mock_ctx, mock_config):
        """Only emotion specified — other update methods not called."""
        payload = {"user": "test", "assistant": "response"}
        llm_result = {
            "facts": [],
            "goals": [],
            "promises": [],
            "context_update": {"emotion": "sad", "emotion_intensity": 0.3},
            "inventory_update": {},
        }

        with patch("nous.application.chat.memory_llm.MemoryLLM") as mock_llm:
            instance = mock_llm.return_value
            instance.process = AsyncMock(return_value=llm_result)

            await run_memory_llm(mock_ctx, mock_config, payload)

        mock_ctx.persona_service.update_emotion.assert_called_once_with(
            "test_persona",
            "sad",
            0.3,
            context="llm_suggested",
        )
        mock_ctx.persona_service.update_physical_state.assert_not_called()
        mock_ctx.persona_service.update_persona_info.assert_not_called()

    @pytest.mark.asyncio
    async def test_context_update_physical_state_only(self, mock_ctx, mock_config):
        """Only physical state fields — emotion not called. physical_state → memory, environment → update_physical_state."""
        payload = {"user": "test", "assistant": "response"}
        llm_result = {
            "facts": [],
            "goals": [],
            "promises": [],
            "context_update": {
                "physical_state": "疲れている",
                "environment": "自宅",
            },
            "inventory_update": {},
        }

        with patch("nous.application.chat.memory_llm.MemoryLLM") as mock_llm:
            instance = mock_llm.return_value
            instance.process = AsyncMock(return_value=llm_result)

            await run_memory_llm(mock_ctx, mock_config, payload)

        mock_ctx.persona_service.update_emotion.assert_not_called()
        # physical_state → memory
        mock_ctx.memory_service.create_memory.assert_any_call(
            content="physical_state: 疲れている",
            tags=["physical_state", "body"],
            importance=0.6,
        )
        # environment → update_physical_state (allowed key)
        mock_ctx.persona_service.update_physical_state.assert_called_once_with(
            "test_persona",
            environment="自宅",
        )
        mock_ctx.persona_service.update_persona_info.assert_not_called()

    @pytest.mark.asyncio
    async def test_context_update_creates_speech_style_memory(self, mock_ctx, mock_config):
        """speech_style → memory, emotion → update_emotion."""
        payload = {"user": "hello", "assistant": "hi"}
        llm_result = {
            "facts": [],
            "goals": [],
            "promises": [],
            "context_update": {
                "speech_style": "ツンデレ口調",
                "emotion": "joy",
            },
            "inventory_update": {},
        }

        with patch("nous.application.chat.memory_llm.MemoryLLM") as mock_llm:
            instance = mock_llm.return_value
            instance.process = AsyncMock(return_value=llm_result)
            await run_memory_llm(mock_ctx, mock_config, payload)

        mock_ctx.memory_service.create_memory.assert_any_call(
            content="speech_style: ツンデレ口調",
            tags=["speech_style", "speech"],
            importance=0.6,
        )

    @pytest.mark.asyncio
    async def test_context_update_no_state_change_skips_memory(self, mock_ctx, mock_config):
        """Empty context_update → no create_memory calls."""
        payload = {"user": "test", "assistant": "response"}
        llm_result = {
            "facts": [],
            "goals": [],
            "promises": [],
            "context_update": {},
            "inventory_update": {},
        }

        with patch("nous.application.chat.memory_llm.MemoryLLM") as mock_llm:
            instance = mock_llm.return_value
            instance.process = AsyncMock(return_value=llm_result)
            await run_memory_llm(mock_ctx, mock_config, payload)

        # create_memory should not be called with speech_style/physical_state/mental_state keys
        for call in mock_ctx.memory_service.create_memory.call_args_list:
            _, kwargs = call
            content = kwargs.get("content", "")
            assert not any(
                content.startswith(prefix) for prefix in ("speech_style:", "physical_state:", "mental_state:")
            ), f"Memory should not be created: {content}"

    @pytest.mark.asyncio
    async def test_context_update_none_state_skips_memory(self, mock_ctx, mock_config):
        """None values for speech_style/physical_state/mental_state → no memory creation."""
        payload = {"user": "test", "assistant": "response"}
        llm_result = {
            "facts": [],
            "goals": [],
            "promises": [],
            "context_update": {"speech_style": None, "physical_state": None, "mental_state": None},
            "inventory_update": {},
        }

        with patch("nous.application.chat.memory_llm.MemoryLLM") as mock_llm:
            instance = mock_llm.return_value
            instance.process = AsyncMock(return_value=llm_result)
            await run_memory_llm(mock_ctx, mock_config, payload)

        # None values should not create memories
        for call in mock_ctx.memory_service.create_memory.call_args_list:
            _, kwargs = call
            content = kwargs.get("content", "")
            assert not any(
                content.startswith(prefix) for prefix in ("speech_style:", "physical_state:", "mental_state:")
            ), f"Memory should not be created for None: {content}"
