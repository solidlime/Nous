"""tests/unit/test_context_sections.py — _build_context_section の importance セクションと
prompt.py の優先順位文面のテスト。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from nous.domain.shared.result import Success


def _make_memory(content: str, tags: list[str] | None = None):
    m = MagicMock()
    m.key = "k0"
    m.content = content
    m.tags = tags or []
    m.created_at = None
    m.updated_at = None
    return m


def _make_ctx(top_memories=None):
    ctx = MagicMock()
    ctx.persona = "test"
    ctx.memory_service = MagicMock()
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

    # 戻り値は (state_body, core_body)。本テストは平坦化した文字列で検査する
    state_body, core_body = await _build_context_section(ctx, state, compress_mode=compress_mode)
    return "\n".join(filter(None, (state_body, core_body)))


class TestTopImportanceSection:
    """get_top_by_importance の結果が「重要な記憶」として注入されること。"""

    @pytest.mark.asyncio
    async def test_top_memories_injected(self):
        ctx = _make_ctx(top_memories=[_make_memory("ラウラというニックネームで呼ばれている")])
        result = await _build(ctx, _make_state())
        assert "重要: ラウラというニックネームで呼ばれている" in result

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
        assert "重要:" in result
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
        assert "身体: " in result
        assert "重要:" not in result


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
        for name in ("current_state", "core_memory", "recalled_memory", "recent_turns"):
            assert name in CHARACTER_ADHERENCE_BLOCK
        assert "矛盾しないこと" in CHARACTER_ADHERENCE_BLOCK
        assert "列挙・読み上げはしない" in CHARACTER_ADHERENCE_BLOCK

    def test_persona_format_still_works(self):
        from nous.application.chat.pipeline.prompt import CHARACTER_ADHERENCE_BLOCK

        rendered = CHARACTER_ADHERENCE_BLOCK.format(persona="ヘルタ")
        assert "ヘルタ" in rendered


class TestBodyActionHint:
    """身体の数値から導いた「身体の傾向」行（助言のみ・虚弱時だけ）。"""

    @pytest.mark.asyncio
    async def test_hint_rendered_when_fatigued(self):
        state = _make_state()
        state.fatigue = 0.8
        result = await _build(_make_ctx(), state)
        assert "身体の傾向:" in result
        assert "強い疲労" in result

    @pytest.mark.asyncio
    async def test_no_hint_when_healthy(self):
        state = _make_state()
        state.fatigue = 0.1
        state.arousal = 0.2
        result = await _build(_make_ctx(), state)
        assert "身体の傾向:" not in result

    @pytest.mark.asyncio
    async def test_place_line_still_present(self):
        """場所の行は従来どおり出る（助言行の追加で消えない）。"""
        state = _make_state()
        state.environment = "ラウンジ"
        state.fatigue = 0.9
        result = await _build(_make_ctx(), state)
        assert "場所: ラウンジ" in result
        assert "ラウンジにいる。" in result  # #42: カタログの行動ヒントが 1 行入る
        assert "身体の傾向:" in result


class TestFreeTextBodyState:
    """物理・精神の自由記述も次ターンの文脈に戻る（数値だけでは書き直しの圧力になる）."""

    async def test_physical_and_mental_state_are_injected(self):
        state = _make_state()
        state.physical_state = "肩が重い"
        state.mental_state = "昨日の会話を引きずっている"

        section = await _build(_make_ctx(), state)

        assert "体調: 肩が重い" in section
        assert "心境: 昨日の会話を引きずっている" in section

    async def test_empty_strings_are_skipped(self):
        state = _make_state()
        state.physical_state = "   "
        state.mental_state = None

        section = await _build(_make_ctx(), state)

        assert "体調:" not in section
        assert "心境:" not in section

    async def test_appearance_is_not_injected(self):
        """見た目 の長文行は廃止（装備行と重複し、毎ターン文脈を圧迫していた）。"""
        state = _make_state()
        state.appearance = "A" * 400

        section = await _build(_make_ctx(), state)

        assert "見た目:" not in section
        assert "A" * 400 not in section
        assert state.appearance == "A" * 400  # state 側の値は無傷


class TestRelativeTimeOnCoreLines:
    """#149: 重要/洞察/癖/未了 の行末に相対時刻を添える（いつの記憶か分かるように）。"""

    @pytest.mark.asyncio
    async def test_importance_line_has_relative_time(self):
        m = _make_memory("古い記憶")
        m.created_at = datetime.now(tz=UTC) - timedelta(days=3)
        result = await _build(_make_ctx(top_memories=[m]), _make_state())
        assert "重要: 古い記憶（k0, 3日前）" in result

    @pytest.mark.asyncio
    async def test_unknown_timestamp_keeps_bare_key(self):
        result = await _build(_make_ctx(top_memories=[_make_memory("時刻不明")]), _make_state())
        assert "重要: 時刻不明（k0）" in result


def _carry_memory(content: str, key: str = "c0", valid_until=None):
    m = _make_memory(content, tags=["journal:carry"])
    m.key = key
    m.valid_until = valid_until
    return m


class TestJournalCarrySection:
    """#147: 日記の「伝えたいこと」を current_state に最大 2 件まで。"""

    def _ctx(self, carry):
        ctx = _make_ctx()
        ctx.memory_service.get_by_tags.side_effect = lambda tags, *a, **k: (
            Success(carry) if "journal:carry" in tags else Success([])
        )
        return ctx

    @pytest.mark.asyncio
    async def test_carry_lines_capped_at_two(self):
        carry = [_carry_memory(f"伝えたいこと{i}", key=f"c{i}") for i in range(3)]
        result = await _build(self._ctx(carry), _make_state())
        assert result.count("伝えたい: ") == 2

    @pytest.mark.asyncio
    async def test_expired_carry_is_skipped(self):
        carry = [
            _carry_memory("期限切れの伝言", valid_until=datetime.now(tz=UTC) - timedelta(days=1)),
            _carry_memory("新しい伝言", key="c1", valid_until=datetime.now(tz=UTC) + timedelta(days=1)),
        ]
        result = await _build(self._ctx(carry), _make_state())
        assert "期限切れの伝言" not in result
        assert "新しい伝言" in result
