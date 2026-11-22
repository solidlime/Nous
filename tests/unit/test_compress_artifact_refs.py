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

    def test_finds_refs_inside_segment_expanded_tool_content(self):
        """JSON 文字列でない（dict 展開後の）tool content でも拾える。"""
        removed = [_tool('{"status": "ok", "artifact_path": "/data/x.txt"}')]
        assert TrimmerMixin._collect_artifact_refs(removed) == ["/data/x.txt"]
