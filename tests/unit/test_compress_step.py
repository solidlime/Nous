"""CompressStep: 予算駆動の永続 evict（Stage 3'）のテスト。

Stage 0（固定窓切り詰め）・Stage 2（system トリム）・force_compress は廃止。
圧縮は Stage 1（古い tool 結果のステータス化）→ Stage 3'（node 単位の永続 evict +
差分要約）の 2 段のみ。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nous.application.chat.tree_session import TreeSessionWindow
from nous.infrastructure.llm.base import LLMMessage
from nous.infrastructure.llm.token_counter import TokenCounter


def _dummy_app_context():
    return MagicMock()


def _dummy_turn_ctx(system_prompt: str = "", volatile: str = "", user_message: str = "今回の質問"):
    ctx = MagicMock()
    ctx.system_prompt = system_prompt
    ctx.volatile_context = volatile
    ctx.user_message = user_message
    ctx.messages = []
    return ctx


def _make_chat_config(**overrides):
    from nous.domain.config.chat_config import ChatConfig

    defaults = {
        "persona": "test",
        "provider": "openrouter",
        "model": "openai/gpt-4o",
        "context_max_tokens": 200,  # Very low to force compression
        "context_compression_threshold": 1.0,
        "context_compress_history": True,
        "context_use_llm_summary": False,
    }
    defaults.update(overrides)
    return ChatConfig(**defaults)


def _long_messages(num_pairs: int = 10) -> list[LLMMessage]:
    msgs: list[LLMMessage] = []
    for i in range(num_pairs):
        msgs.append(LLMMessage(role="user", content=f"ターン{i}のユーザー発言。" + "たくさんのテキスト。" * 20))
        msgs.append(LLMMessage(role="assistant", content=f"ターン{i}の回答。" + "それなりの長さの応答。" * 20))
    return msgs


def _window(msgs: list[LLMMessage], **kwargs) -> TreeSessionWindow:
    w = TreeSessionWindow(**kwargs)
    for m in msgs:
        w.add(m.role, m.content or "", tool_calls=m.tool_calls)
    return w


def _messages_with_tool_results() -> list[LLMMessage]:
    msgs: list[LLMMessage] = []
    for i in range(8):
        msgs.append(LLMMessage(role="user", content=f"User message {i}" * 20))
        msgs.append(
            LLMMessage(
                role="assistant",
                content=f"Assistant response {i}" * 20,
                tool_calls=[{"id": f"call_{i}", "name": "memory_search", "input": {"query": f"test {i}"}}],
            )
        )
        msgs.append(LLMMessage(role="tool", content=f"Tool result {i}: " + "x" * 500, tool_call_id=f"call_{i}"))
    return msgs


# ──────────────────────────────────────────────
# TokenCounter（据え置き・回帰防止）
# ──────────────────────────────────────────────


class TestTokenCounter:
    def test_count_empty(self):
        assert TokenCounter().count("") == 0

    def test_count_messages(self):
        msgs = [
            LLMMessage(role="user", content="Hello"),
            LLMMessage(role="assistant", content="Hi there!"),
            LLMMessage(role="tool", content="result data here", tool_call_id="call_1"),
        ]
        assert TokenCounter().count_messages(msgs, "System prompt text") > 0

    def test_get_model_max_gpt4o(self):
        assert TokenCounter.get_model_max_tokens("gpt-4o") == 128_000

    def test_get_model_max_claude(self):
        assert TokenCounter.get_model_max_tokens("claude-opus-4-5") == 200_000


# ──────────────────────────────────────────────
# Stage 1 + 予算判定
# ──────────────────────────────────────────────


class TestBudgetGate:
    @pytest.mark.asyncio
    async def test_no_compression_when_under_budget(self):
        config = _make_chat_config(context_max_tokens=1_000_000)
        msgs = _long_messages(num_pairs=3)
        session = _window(msgs)

        result = await _run(config, _dummy_turn_ctx(), session)

        assert result == session.get_labeled_messages()

    @pytest.mark.asyncio
    async def test_no_session_sends_as_is(self):
        """session 未指定（後方互換）でもクラッシュせず素通しする。"""
        from nous.application.chat.pipeline.compress import CompressStep

        config = _make_chat_config(context_max_tokens=200)
        msgs = _long_messages(num_pairs=10)
        tctx = _dummy_turn_ctx()

        result = await CompressStep().run(_dummy_app_context(), config, tctx, msgs)

        assert len(result) == len(msgs)

    @pytest.mark.asyncio
    async def test_budget_includes_volatile_and_user(self):
        """揮発ブロックと最新 user 発言も予算に含める。"""
        config = _make_chat_config(context_max_tokens=2_000)
        msgs = _long_messages(num_pairs=1)
        session = _window(msgs)

        # 会話だけなら予算内、揮発が巨大なら超過
        tctx = _dummy_turn_ctx(volatile="x" * 20_000)
        with patch.object(
            __import__("nous.application.chat.pipeline.compress", fromlist=["CompressStep"]).CompressStep,
            "_stage3_evict",
            new_callable=AsyncMock,
        ) as mock_evict:
            mock_evict.return_value = session.get_labeled_messages()
            from nous.application.chat.pipeline.compress import CompressStep

            await CompressStep().run(_dummy_app_context(), config, tctx, session.get_labeled_messages(), session)
            mock_evict.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_stage1_replaces_old_tool_results(self):
        config = _make_chat_config(context_max_tokens=1, context_use_llm_summary=False)
        session = _window(_messages_with_tool_results())
        tctx = _dummy_turn_ctx()

        with patch.object(
            __import__("nous.application.chat.pipeline.compress", fromlist=["CompressStep"]).CompressStep,
            "_stage3_evict",
            new_callable=AsyncMock,
        ) as mock_evict:
            from nous.application.chat.pipeline.compress import CompressStep

            mock_evict.side_effect = lambda *a, **kw: session.get_labeled_messages()
            result = await CompressStep().run(
                _dummy_app_context(), config, tctx, session.get_labeled_messages(), session
            )

        replaced = [m for m in result if m.role == "tool" and "ツール実行" in (m.content or "")]
        assert replaced, "古い tool 結果はステータスに置換される"
        # 直近の tool 結果は原文のまま残る
        intact = [m for m in result if m.role == "tool" and "x" * 100 in (m.content or "")]
        assert intact, "直近 3 ターン分の tool 結果は原文保持"


async def _run(config, tctx, session) -> list[LLMMessage]:
    from nous.application.chat.pipeline.compress import CompressStep

    return await CompressStep().run(_dummy_app_context(), config, tctx, session.get_labeled_messages(), session)


# ──────────────────────────────────────────────
# Stage 3': node 単位の永続 evict + 差分要約
# ──────────────────────────────────────────────

_TAG = "<conversation_history_summary>"


def _pairs(num_pairs: int, size: int = 120) -> list[LLMMessage]:
    """各メッセージ size 文字の素直な会話（user/assistant 交互）。"""
    msgs: list[LLMMessage] = []
    for i in range(num_pairs):
        msgs.append(LLMMessage(role="user", content=f"質問{i}:" + "u" * size))
        msgs.append(LLMMessage(role="assistant", content=f"回答{i}:" + "a" * size))
    return msgs


class TestStage3Evict:
    @pytest.mark.asyncio
    async def test_evicts_on_user_boundary_and_persists_summary(self):
        from nous.application.chat.pipeline.compress import CompressStep

        config = _make_chat_config(context_max_tokens=300, context_use_llm_summary=True, api_key="sk-test")
        session = _window(_pairs(6))
        tctx = _dummy_turn_ctx()

        with patch.object(CompressStep, "_summarize_old_turns", new_callable=AsyncMock) as mock_sum:
            mock_sum.return_value = "差分要約の本文"
            result = await CompressStep().run(
                _dummy_app_context(), config, tctx, session.get_labeled_messages(), session
            )

        mock_sum.assert_awaited_once()
        # 切込は必ず user 境界（残りの先頭が user）
        assert session.get_active_path()[0]["role"] == "user"
        # 窓は実際に縮んでいる
        assert len(session.get_active_path()) < 12
        assert len(result) < 12
        # 差分要約は window に永続化され、揮発ブロックにも載る
        assert "差分要約の本文" in session.history_summary
        assert _TAG in tctx.volatile_context
        assert "差分要約の本文" in tctx.volatile_context

    @pytest.mark.asyncio
    async def test_evict_passes_expanded_slice_and_refs(self):
        """evict 切片は LLMMessage 展開済み・refs 付きで要約へ渡る。"""
        from nous.application.chat.pipeline.compress import CompressStep

        config = _make_chat_config(context_max_tokens=350, context_use_llm_summary=True, api_key="sk-test")
        session = TreeSessionWindow()
        session.add("user", "古い質問" + "u" * 400)
        session.add(
            "assistant",
            "",
            segments=[
                {"type": "tool_call", "id": "c1", "name": "attach_file", "input": {}},
                {"type": "tool_result", "id": "c1", "result": '{"status":"ok","artifact_path":"/data/old.txt"}'},
                {"type": "text", "content": "添付しました"},
            ],
        )
        session.add("user", "新しい質問" + "u" * 400)
        session.add("assistant", "新しい回答" + "a" * 400)
        session.add("user", "最新の質問")
        session.add("assistant", "最新の回答")

        tctx = _dummy_turn_ctx()
        with patch.object(CompressStep, "_summarize_old_turns", new_callable=AsyncMock) as mock_sum:
            mock_sum.return_value = "要約X"
            await CompressStep().run(_dummy_app_context(), config, tctx, session.get_labeled_messages(), session)

        removed = mock_sum.call_args.kwargs["removed"]
        # segments が展開され tool メッセージが現れる
        assert any(m.role == "tool" for m in removed)
        assert mock_sum.call_args.kwargs["refs"] == ["/data/old.txt"]

    @pytest.mark.asyncio
    async def test_fallback_note_when_summary_disabled(self):
        from nous.application.chat.pipeline.compress import CompressStep

        config = _make_chat_config(context_max_tokens=300, context_use_llm_summary=False)
        session = _window(_pairs(6))
        tctx = _dummy_turn_ctx()

        await CompressStep().run(_dummy_app_context(), config, tctx, session.get_labeled_messages(), session)

        # 決定論的フォールバック（「記憶として保存済み」は偽になるため使わない）
        assert "トークン予算超過により省略されています" in session.history_summary
        assert "记忆" not in session.history_summary
        assert "記憶として保存済み" not in session.history_summary

    @pytest.mark.asyncio
    async def test_fallback_when_llm_fails(self):
        from nous.application.chat.pipeline.compress import CompressStep

        config = _make_chat_config(context_max_tokens=300, context_use_llm_summary=True, api_key="sk-test")
        session = _window(_pairs(6))
        tctx = _dummy_turn_ctx()

        with patch.object(CompressStep, "_summarize_old_turns", new_callable=AsyncMock) as mock_sum:
            mock_sum.side_effect = RuntimeError("provider down")
            await CompressStep().run(_dummy_app_context(), config, tctx, session.get_labeled_messages(), session)

        assert "トークン予算超過により省略されています" in session.history_summary
        assert _TAG in tctx.volatile_context

    @pytest.mark.asyncio
    async def test_no_user_boundary_does_not_evict(self):
        """終了条件: active path に user が無い → 切らない。"""
        from nous.application.chat.pipeline.compress import CompressStep

        config = _make_chat_config(context_max_tokens=200, context_use_llm_summary=False)
        session = TreeSessionWindow()
        session.add("assistant", "独り言" + "x" * 400)
        session.add("assistant", "独り言" + "x" * 400)
        tctx = _dummy_turn_ctx()

        await CompressStep().run(_dummy_app_context(), config, tctx, session.get_labeled_messages(), session)

        assert len(session.get_active_path()) == 2
        assert session.history_summary == ""

    @pytest.mark.asyncio
    async def test_huge_single_message_is_not_evicted_past(self):
        """終了条件: 単一メッセージが予算超過 → それ以降は切らない（最善努力）。"""
        from nous.application.chat.pipeline.compress import CompressStep

        config = _make_chat_config(context_max_tokens=200, context_use_llm_summary=False)
        session = TreeSessionWindow()
        session.add("user", "小さい質問")
        session.add("user", "x" * 5000)  # 単体で予算超過
        session.add("assistant", "回答")
        session.add("user", "次の質問")
        session.add("assistant", "次の回答")
        tctx = _dummy_turn_ctx()

        await CompressStep().run(_dummy_app_context(), config, tctx, session.get_labeled_messages(), session)

        remaining = session.get_active_path()
        # 巨大メッセージ以降（4件）は残る。切るのは手前の1件のみ。
        assert len(remaining) == 4
        assert remaining[0]["content"] == "x" * 5000

    @pytest.mark.asyncio
    async def test_prior_summary_reinjected_under_budget(self):
        """前ターンの要約は予算内でも揮発ブロックに載る（毎ターン再送）。"""
        from nous.application.chat.pipeline.compress import CompressStep

        config = _make_chat_config(context_max_tokens=1_000_000)
        session = _window(_pairs(2))
        session.append_history_summary("前ターンの要約")
        tctx = _dummy_turn_ctx()

        await CompressStep().run(_dummy_app_context(), config, tctx, session.get_labeled_messages(), session)

        assert _TAG in tctx.volatile_context
        assert "前ターンの要約" in tctx.volatile_context
        # 揮発ブロック既存内容を壊さない
        assert tctx.volatile_context.startswith(_TAG) or _TAG in tctx.volatile_context


class TestHistorySummaryFrame:
    def test_frames_into_volatile(self):
        from nous.application.chat.pipeline.compress import CompressStep

        tctx = _dummy_turn_ctx(volatile="既存の揮発ブロック")
        CompressStep._apply_history_summary(tctx, "要約本文")

        assert "既存の揮発ブロック" in tctx.volatile_context
        assert _TAG in tctx.volatile_context
        assert "</conversation_history_summary>" in tctx.volatile_context
        assert "要約本文" in tctx.volatile_context
        assert "最新のユーザー指示と <precedence> が優先" in tctx.volatile_context

    def test_replaces_existing_tag_in_place(self):
        from nous.application.chat.pipeline.compress import CompressStep

        tctx = _dummy_turn_ctx()
        CompressStep._apply_history_summary(tctx, "一回目")
        CompressStep._apply_history_summary(tctx, "二回目")

        assert tctx.volatile_context.count(_TAG) == 1
        assert "二回目" in tctx.volatile_context
        assert "一回目" not in tctx.volatile_context

    def test_empty_body_is_noop(self):
        from nous.application.chat.pipeline.compress import CompressStep

        tctx = _dummy_turn_ctx(volatile="base")
        CompressStep._apply_history_summary(tctx, "")
        assert tctx.volatile_context == "base"


class TestFallbackNote:
    def test_counts_and_hint(self):
        from nous.application.chat.pipeline.compress import CompressStep

        note = CompressStep._fallback_note(7, [])
        assert "7 件" in note
        assert "memory_search" in note

    def test_includes_refs(self):
        from nous.application.chat.pipeline.compress import CompressStep

        note = CompressStep._fallback_note(3, ["/data/a.txt", "/logs/b.log"])
        assert "/data/a.txt" in note
        assert "/logs/b.log" in note


# ──────────────────────────────────────────────
# TreeSessionWindow: 永続基線
# ──────────────────────────────────────────────


class TestTreeSessionHistorySummary:
    def test_append_merges_with_separator(self):
        w = TreeSessionWindow()
        w.append_history_summary("古い")
        merged = w.append_history_summary("新しい")
        assert merged == "古い\n---\n新しい"
        assert w.history_summary == merged

    def test_caps_at_4000_chars_dropping_oldest(self):
        from nous.application.chat.tree_session import HISTORY_SUMMARY_MAX_CHARS

        w = TreeSessionWindow()
        w.append_history_summary("A" * 3000)
        w.append_history_summary("B" * 3000)

        assert len(w.history_summary) == HISTORY_SUMMARY_MAX_CHARS
        assert w.history_summary.endswith("B" * 3000)

    def test_empty_delta_keeps_summary(self):
        w = TreeSessionWindow()
        w.append_history_summary("既存")
        assert w.append_history_summary("") == "既存"

    def test_evict_path_head_returns_nodes_and_shrinks(self):
        w = _window(_pairs(3))
        evicted = w.evict_path_head(2)

        assert len(evicted) == 2
        assert [n["role"] for n in evicted] == ["user", "assistant"]
        assert len(w.get_active_path()) == 4

    def test_evict_path_head_does_not_fire_callback(self):
        w = _window(_pairs(3))
        seen: list = []
        w.evict_callback = seen.append

        w.evict_path_head(2)

        assert seen == []

    def test_evict_keeps_at_least_one_node(self):
        w = _window(_pairs(1))
        w.evict_path_head(99)
        assert len(w.get_active_path()) == 1

    def test_payload_roundtrip_preserves_summary(self):
        import json

        w = TreeSessionWindow()
        w._db = MagicMock()
        w._persona = "p"
        w._session_id = "s"
        captured: dict = {}

        def _execute(sql, params):
            captured["params"] = params

        w._db.execute = _execute
        w.add("user", "hello")
        w.append_history_summary("積んだ要約")

        payload = json.loads(captured["params"][2])
        assert payload["history_summary"] == "積んだ要約"
