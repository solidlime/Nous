"""tests/unit/test_context_sections.py — _build_context_section の promise/importance セクションと
prompt.py の優先順位文面のテスト。"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from nous.domain.shared.result import Success


def _make_memory(content: str, tags: list[str] | None = None):
    m = MagicMock()
    m.content = content
    m.tags = tags or []
    m.created_at = None
    m.updated_at = None
    return m


def _make_ctx(promises=None, top_memories=None):
    ctx = MagicMock()
    ctx.persona = "test"
    ctx.memory_service = MagicMock()
    ctx.memory_service.get_by_tags.return_value = Success(promises or [])
    ctx.memory_service.get_top_by_importance.return_value = Success(top_memories or [])
    ctx.persona_service = MagicMock()
    ctx.persona_service.get_emotion_history.return_value = Success([])
    ctx.equipment_service = MagicMock()
    ctx.equipment_service.get_equipment.return_value = Success({})
    return ctx


def _make_state():
    state = MagicMock()
    state.last_conversation_time = None
    state.emotion = None
    state.mental_state = None
    state.physical_state = None
    state.environment = None
    state.relationship_status = None
    state.user_info = {}
    state.persona_info = {}
    state.fatigue = None
    state.pain = None
    state.arousal = None
    return state


async def _build(ctx, state, compress_mode="auto"):
    from nous.application.chat.pipeline.prepare import _build_context_section

    return await _build_context_section(ctx, state, compress_mode=compress_mode)


class TestPromiseSection:
    """promise タグの記憶が「前からの約束」として注入されること。"""

    @pytest.mark.asyncio
    async def test_promise_memories_injected(self):
        ctx = _make_ctx(promises=[_make_memory("週末に試験結果を報告する")])
        result = await _build(ctx, _make_state())
        assert "前からの約束:" in result
        assert "🤝 週末に試験結果を報告する" in result

    @pytest.mark.asyncio
    async def test_promise_fetched_with_promise_tag(self):
        ctx = _make_ctx(promises=[_make_memory("x")])
        await _build(ctx, _make_state())
        ctx.memory_service.get_by_tags.assert_any_call(["promise"])

    @pytest.mark.asyncio
    async def test_promise_light_mode_skipped(self):
        """light モードでは約束セクションをスキップする。"""
        ctx = _make_ctx(promises=[_make_memory("週末の約束")])
        result = await _build(ctx, _make_state(), compress_mode="light")
        assert "前からの約束:" not in result
        assert "週末の約束" not in result


class TestTopImportanceSection:
    """get_top_by_importance の結果が「重要な記憶」として注入されること。"""

    @pytest.mark.asyncio
    async def test_top_memories_injected(self):
        ctx = _make_ctx(top_memories=[_make_memory("ラウラというニックネームで呼ばれている")])
        result = await _build(ctx, _make_state())
        assert "重要な記憶:" in result
        assert "📖 ラウラというニックネームで呼ばれている" in result

    @pytest.mark.asyncio
    async def test_auto_mode_requests_five(self):
        ctx = _make_ctx(top_memories=[_make_memory(f"m{i}") for i in range(5)])
        await _build(ctx, _make_state())
        ctx.memory_service.get_top_by_importance.assert_called_once_with(5)

    @pytest.mark.asyncio
    async def test_light_mode_kept_with_three(self):
        """light モードでも重要な記憶は残る（3件に減らす）。"""
        ctx = _make_ctx(top_memories=[_make_memory(f"重要 {i}") for i in range(5)])
        result = await _build(ctx, _make_state(), compress_mode="light")
        assert "重要な記憶:" in result
        ctx.memory_service.get_top_by_importance.assert_called_once_with(3)
        assert "重要 3" not in result  # 3件に丸められている
        assert "重要 0" in result

    @pytest.mark.asyncio
    async def test_long_content_truncated_to_200(self):
        ctx = _make_ctx(top_memories=[_make_memory("あ" * 300)])
        result = await _build(ctx, _make_state())
        assert "あ" * 300 not in result
        assert ("あ" * 200 + "...") in result

    @pytest.mark.asyncio
    async def test_fetch_failure_fail_soft(self):
        """get_top_by_importance が例外を投げてもセクション構築は失敗しない。"""
        ctx = _make_ctx()
        ctx.memory_service.get_top_by_importance.side_effect = RuntimeError("boom")
        result = await _build(ctx, _make_state())
        assert "【現在の状態】" in result
        assert "重要な記憶:" not in result


class TestPrecedenceBlock:
    """PRECEDENCE_BLOCK にセッション事実・ユーザー指示の優先文面が含まれること。"""

    def test_session_facts_ranked_second(self):
        from nous.application.chat.pipeline.prompt import PRECEDENCE_BLOCK

        assert "現在のセッション内の事実" in PRECEDENCE_BLOCK
        assert "ユーザーの明示的な指示" in PRECEDENCE_BLOCK
        # セッション事実はキャラ厳守より上位
        assert PRECEDENCE_BLOCK.index("セッション内の事実") < PRECEDENCE_BLOCK.index("キャラクター厳守")

    def test_contradiction_rule_present(self):
        from nous.application.chat.pipeline.prompt import PRECEDENCE_BLOCK

        assert "注入文脈を黙って信奉しない" in PRECEDENCE_BLOCK
        assert "答えられない場合はそう伝えてよい" in PRECEDENCE_BLOCK


class TestCharacterAdherenceConsistency:
    """CHARACTER_ADHERENCE_BLOCK に注入データとの矛盾禁止文が含まれること。"""

    def test_consistency_lines_present(self):
        from nous.application.chat.pipeline.prompt import CHARACTER_ADHERENCE_BLOCK

        # タグ名はリテラル <xx> で書かない（tag-pairing ガード §4.5 の誤検知防止）
        for name in ("current_state", "related_memories", "time_context"):
            assert name in CHARACTER_ADHERENCE_BLOCK
        assert "矛盾しないこと" in CHARACTER_ADHERENCE_BLOCK
        assert "列挙・読み上げはしない" in CHARACTER_ADHERENCE_BLOCK

    def test_persona_format_still_works(self):
        from nous.application.chat.pipeline.prompt import CHARACTER_ADHERENCE_BLOCK

        rendered = CHARACTER_ADHERENCE_BLOCK.format(persona="ヘルタ")
        assert "ヘルタ" in rendered
