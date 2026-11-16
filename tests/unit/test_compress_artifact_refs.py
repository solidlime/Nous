"""切り詰め時にツール結果の保存先パスを要約へ残す（原文への復帰路）。"""

from __future__ import annotations

from nous.application.chat.pipeline.trimmer import TrimmerMixin
from nous.infrastructure.llm.base import LLMMessage


def _tool(content: str) -> LLMMessage:
    return LLMMessage(role="tool", content=content, tool_call_id="t")


class TestCollectArtifactRefs:
    def test_picks_artifact_and_log_paths(self):
        removed = [
            _tool('{"status":"ok","artifact_path":"/data/a.txt"}'),
            _tool('{"status":"ok","log_path":"/logs/b.log"}'),
        ]
        assert TrimmerMixin._collect_artifact_refs(removed) == ["/data/a.txt", "/logs/b.log"]

    def test_dedups_and_keeps_order(self):
        removed = [
            _tool('{"artifact_path":"/same"}'),
            _tool('{"artifact_path":"/same"}'),
            _tool('{"artifact_path":"/other"}'),
        ]
        assert TrimmerMixin._collect_artifact_refs(removed) == ["/same", "/other"]

    def test_ignores_messages_without_paths(self):
        assert TrimmerMixin._collect_artifact_refs([_tool("plain output")]) == []

    def test_caps_results(self):
        removed = [_tool(f'{{"artifact_path":"/f{i}"}}') for i in range(30)]
        assert len(TrimmerMixin._collect_artifact_refs(removed)) == 20


class TestTruncationHighlightsIncludeRefs:
    def test_refs_survive_truncation(self):
        msgs = [
            _tool('{"artifact_path":"/data/big.txt"}'),
            LLMMessage(role="user", content="古い質問"),
            LLMMessage(role="assistant", content="古い回答"),
            LLMMessage(role="user", content="新しい質問"),
            LLMMessage(role="assistant", content="新しい回答"),
        ]
        result, highlights, removed = TrimmerMixin._truncate_old_messages(msgs, keep_recent_turns=1)
        assert len(result) == 2
        assert removed
        assert "/data/big.txt" in highlights
        assert "参照ファイル" in highlights

    def test_no_refs_no_section(self):
        msgs = [
            LLMMessage(role="user", content="古い質問"),
            LLMMessage(role="assistant", content="古い回答"),
            LLMMessage(role="user", content="新しい質問"),
            LLMMessage(role="assistant", content="新しい回答"),
        ]
        _result, highlights, _removed = TrimmerMixin._truncate_old_messages(msgs, keep_recent_turns=1)
        assert "/" not in highlights or "参照ファイル" not in highlights
