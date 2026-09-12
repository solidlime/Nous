"""curiosity 探索の補助ヘルパーテスト（全開放方針に伴い allowlist テストを置換）。

- `_parse_json_object`: 単行/複数行フェンス剥ぎ。
- `_compact_search_result`: 検索系結果の server__name 候補リスト化。
"""

from __future__ import annotations

import json

from nous.application.chat.introspection import _compact_search_result, _parse_json_object


class TestParseJsonObjectFence:
    def test_single_line_json_fence(self):
        # LLM が ```json {...}``` を 1 行で返すケース（旧実装は空文字に潰れていた）。
        assert _parse_json_object('```json {"tool_name": "x"}```') == {"tool_name": "x"}

    def test_single_line_bare_fence(self):
        assert _parse_json_object('``` {"done": true}```') == {"done": True}

    def test_single_line_fence_with_space_before_json(self):
        # "``` json"（空白入り）も剥がす。
        assert _parse_json_object('``` json {"done": true}```') == {"done": True}

    def test_multiline_json_fence(self):
        text = '```json\n{"tool_name": "x", "args": {}}\n```'
        assert _parse_json_object(text) == {"tool_name": "x", "args": {}}

    def test_raw_json(self):
        assert _parse_json_object('{"done": true}') == {"done": True}

    def test_broken_returns_none(self):
        assert _parse_json_object("not json") is None
        assert _parse_json_object("") is None
        # dict 以外は None
        assert _parse_json_object("[1, 2]") is None


class TestCompactSearchResult:
    def test_results_key_real_shape(self):
        # 実ログの search_tools 返り値形状。server + name → server__name。
        raw = json.dumps(
            {
                "results": [
                    {"server": "Exa", "name": "web_search_exa", "description": "..."},
                    {"server": "mcp-hub", "name": "execute_tool"},
                ]
            }
        )
        assert _compact_search_result(raw) == "Exa__web_search_exa, mcp-hub__execute_tool"

    def test_results_key_name_only(self):
        raw = json.dumps({"results": [{"name": "memory_read"}, {"name": "memory_search"}]})
        assert _compact_search_result(raw) == "memory_read, memory_search"

    def test_tools_dict_form(self):
        raw = json.dumps(
            {
                "tools": [
                    {"server": "mcp-hub", "name": "search_tools"},
                    {"server": "nous", "name": "memory_search"},
                ]
            }
        )
        assert _compact_search_result(raw) == "mcp-hub__search_tools, nous__memory_search"

    def test_plain_string_items(self):
        assert _compact_search_result(json.dumps({"tools": ["a", "b"]})) == "a, b"

    def test_bare_list_passthrough(self):
        # 裸リストは対応しない（N3: tools/results キー限定）。
        raw = json.dumps([{"server": "nous", "name": "get_context"}])
        assert _compact_search_result(raw) == raw

    def test_non_json_passthrough(self):
        assert _compact_search_result("雲は500トン") == "雲は500トン"

    def test_json_without_names_passthrough(self):
        raw = json.dumps({"ok": True})
        assert _compact_search_result(raw) == raw
