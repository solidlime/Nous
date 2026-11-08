from nous.application.chat.curiosity import _parse_json_object


def test_parse_json_object_code_fence():
    assert _parse_json_object('```json\n{"a": 1}\n```') == {"a": 1}
    assert _parse_json_object("not json") is None
    assert _parse_json_object("[1,2]") is None
