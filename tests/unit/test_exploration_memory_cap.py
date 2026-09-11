from nous.application.chat.introspection import (
    _MAX_CHARS_PER_MEMORY,
    _cap_memory_texts,
    _parse_json_object,
)


class _M:
    def __init__(self, content, tags):
        self.content = content
        self.tags = tags


def test_exploration_memories_get_500_cap():
    long_expl = "x" * 400
    long_norm = "y" * 200
    got = _cap_memory_texts([_M(long_expl, ["exploration", "introspection"]), _M(long_norm, ["preference"])])
    assert got[0] == long_expl  # 探索要約は切断されない (spec G)
    assert got[1] == "y" * _MAX_CHARS_PER_MEMORY


def test_parse_json_object_code_fence():
    assert _parse_json_object('```json\n{"a": 1}\n```') == {"a": 1}
    assert _parse_json_object("not json") is None
    assert _parse_json_object("[1,2]") is None
