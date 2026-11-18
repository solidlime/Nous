"""content に漏れたツール呼び出し記法の除去と復旧。"""

from __future__ import annotations

from nous.infrastructure.llm.tool_markup import ToolMarkupStream, parse_tool_calls

# DeepSeek 系が吐く記法（全角 ｜ で囲む）
BLOCK = (
    "<｜｜DSML｜｜ calls>\n"
    '<｜｜DSML｜｜ invoke name="bash">\n'
    '<｜｜DSML｜｜ parameter name="command" string="true">echo hello</｜｜DSML｜｜ parameter>\n'
    "</｜｜DSML｜｜ invoke>\n"
    "</｜｜DSML｜｜ calls>"
)


def _strip_all(*chunks: str) -> tuple[str, ToolMarkupStream]:
    stream = ToolMarkupStream()
    visible = "".join(stream.strip(c) for c in chunks) + stream.flush()
    return visible, stream


def test_block_is_hidden_from_user():
    visible, _stream = _strip_all("見てる", BLOCK, "のよ")
    assert "DSML" not in visible
    assert "見てる" in visible and "のよ" in visible


def test_chunk_boundaries_do_not_leak():
    # 1文字ずつ届いてもタグの断片が本文に出ない
    visible, _stream = _strip_all(*BLOCK)
    assert "DSML" not in visible
    assert visible.strip() == ""


def test_calls_are_recovered_with_types():
    _visible, stream = _strip_all(BLOCK)
    calls = parse_tool_calls(stream.markup)
    assert calls == [("bash", {"command": "echo hello"})]


def test_integer_and_boolean_params_are_coerced():
    markup = (
        '<｜｜DSML｜｜ invoke name="image_generate">\n'
        '<｜｜DSML｜｜ parameter name="n">2</｜｜DSML｜｜ parameter>\n'
        '<｜｜DSML｜｜ parameter name="self_portrait">true</｜｜DSML｜｜ parameter>\n'
        "</｜｜DSML｜｜ invoke>"
    )
    _visible, stream = _strip_all(markup)
    assert parse_tool_calls(stream.markup) == [
        ("image_generate", {"n": 2, "self_portrait": True}),
    ]


def test_text_after_block_is_kept():
    visible, _stream = _strip_all(BLOCK + "\n終わりだよ")
    assert "終わりだよ" in visible


def test_two_invokes_in_one_block_are_both_recovered():
    # ブロックが連続すると2つ目が本文に漏れる回帰があった
    markup = (
        '<｜｜DSML｜｜ invoke name="bash">'
        '<｜｜DSML｜｜ parameter name="command" string="true">ls</｜｜DSML｜｜ parameter>'
        "</｜｜DSML｜｜ invoke>"
        '<｜｜DSML｜｜ invoke name="image_generate">'
        '<｜｜DSML｜｜ parameter name="n">2</｜｜DSML｜｜ parameter>'
        "</｜｜DSML｜｜ invoke>"
    )
    visible, stream = _strip_all("前 " + markup + " 後")

    assert "DSML" not in visible
    assert parse_tool_calls(stream.markup) == [("bash", {"command": "ls"}), ("image_generate", {"n": 2})]


def test_plain_text_is_untouched():
    visible, stream = _strip_all("普通の本文 <b>タグ</b> もある")
    assert visible == "普通の本文 <b>タグ</b> もある"
    assert stream.markup == ""


def test_unclosed_block_does_not_swallow_forever():
    # 閉じが来ないまま上限を超えたら捨てて、以降の本文は通す
    visible, _stream = _strip_all("<｜｜DSML｜｜ invoke name=" + "x" * 25000, "本文だよ")
    assert "本文だよ" in visible
