"""TrimmerMixin のテスト。

Stage 0（固定窓切り詰め）廃止に伴い、trimmer は
- 境界探索ヘルパー `_adjust_slice_start`（tool 孤児防止）
- `_collect_artifact_refs`（原文への復帰路）
- `_clear_old_tool_results`（Stage 1）
のみを提供する。
"""

from __future__ import annotations

from nous.application.chat.pipeline.trimmer import TrimmerMixin
from nous.infrastructure.llm.base import LLMMessage


def _msg(role: str, content: str = "", tool_calls=None, tool_call_id=None) -> LLMMessage:
    return LLMMessage(role=role, content=content, tool_calls=tool_calls, tool_call_id=tool_call_id)


class TestAdjustSliceStart:
    def test_start_on_assistant_is_unchanged(self):
        msgs = [_msg("user", "q1"), _msg("assistant", "a1"), _msg("user", "q2")]
        assert TrimmerMixin._adjust_slice_start(msgs, -2) == -2

    def test_start_on_tool_widens_to_its_assistant(self):
        msgs = [
            _msg("user", "q1"),
            _msg("assistant", "", tool_calls=[{"id": "c1"}]),
            _msg("tool", "r1", tool_call_id="c1"),
        ]
        assert TrimmerMixin._adjust_slice_start(msgs, -1) == -2
        assert msgs[TrimmerMixin._adjust_slice_start(msgs, -1)].role == "assistant"

    def test_consecutive_tools_widen_over_all(self):
        msgs = [
            _msg("user", "q1"),
            _msg("assistant", "", tool_calls=[{"id": "c1"}]),
            _msg("tool", "r1", tool_call_id="c1"),
            _msg("tool", "r2", tool_call_id="c1"),
        ]
        assert TrimmerMixin._adjust_slice_start(msgs, -1) == -3

    def test_does_not_widen_past_list_head(self):
        msgs = [_msg("tool", "r1", tool_call_id="c1"), _msg("tool", "r2", tool_call_id="c1")]
        # 全件 tool でもクラッシュせず先頭で止まる
        assert TrimmerMixin._adjust_slice_start(msgs, -1) == -2

    def test_zero_start_is_unchanged(self):
        msgs = [_msg("user", "q1")]
        assert TrimmerMixin._adjust_slice_start(msgs, 0) == 0


class TestClearOldToolResults:
    def test_keeps_recent_three_assistant_turns(self):
        msgs: list[LLMMessage] = []
        for i in range(5):
            msgs.append(_msg("user", f"q{i}"))
            msgs.append(_msg("assistant", "", tool_calls=[{"id": f"c{i}"}]))
            msgs.append(_msg("tool", '{"status":"ok","artifact_path":"/d/x"}', tool_call_id=f"c{i}"))
        result = TrimmerMixin._clear_old_tool_results(msgs)
        tool_msgs = [m for m in result if m.role == "tool"]
        assert "[ツール実行: 成功]" in (tool_msgs[0].content or "")
        # 直近3ターンは原文のまま
        assert "/d/x" in (tool_msgs[-1].content or "")
        # tool_call_id は保持される
        assert [m.tool_call_id for m in tool_msgs] == [f"c{i}" for i in range(5)]

    def test_few_assistant_messages_returns_unchanged(self):
        msgs = [
            _msg("user", "q"),
            _msg("assistant", "", tool_calls=[{"id": "c1"}]),
            _msg("tool", "raw", tool_call_id="c1"),
        ]
        assert TrimmerMixin._clear_old_tool_results(msgs) is msgs

    def test_invalid_json_marked_complete(self):
        msgs: list[LLMMessage] = []
        for i in range(5):
            msgs.append(_msg("user", f"q{i}"))
            msgs.append(_msg("assistant", "", tool_calls=[{"id": f"c{i}"}]))
            msgs.append(_msg("tool", "not json", tool_call_id=f"c{i}"))
        result = TrimmerMixin._clear_old_tool_results(msgs)
        assert "[ツール実行: 完了]" in (result[2].content or "")
