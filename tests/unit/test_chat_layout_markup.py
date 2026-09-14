"""チャットタブ HTML の要素契約テスト.

`chat-mode.js` / `avatar.js` が `getElementById` で参照する要素が本番 HTML に
実在することを固定する。検証用の `_dev_*.html` にだけ要素を置いて本番に置き忘れる
事故（`#chat-avatar-stage-ui` が無くログ高さスライダーと表情 UI が生成されない）を防ぐ。
"""

from nous.api.http.sections.chat import render_chat_tab

# chat-mode.js / avatar.js が必須とする要素 ID
REQUIRED_AVATAR_IDS = (
    "chat-avatar-layer",
    "chat-avatar-canvas-container",
    "chat-avatar-model-ui",
    "chat-avatar-model-select",
    "chat-avatar-upload",
    "chat-avatar-upload-btn",
    "chat-avatar-stage-ui",
)


def test_chat_tab_has_all_avatar_elements():
    html = render_chat_tab()
    missing = [i for i in REQUIRED_AVATAR_IDS if f'id="{i}"' not in html]
    assert not missing, f"チャットタブ HTML に要素がありません: {missing}"


def test_stage_ui_is_nested_inside_avatar_layer():
    """#chat-avatar-stage-ui は #chat-avatar-layer の内側にあること.

    layer は通常モードで hidden のため、外側に出すとスライダーが通常モードでも見えてしまう。
    """
    html = render_chat_tab()
    layer = html.index('<div id="chat-avatar-layer"')
    messages = html.index('<div id="chat-messages"')
    assert layer < html.index('id="chat-avatar-stage-ui"') < messages, (
        "#chat-avatar-stage-ui は #chat-avatar-layer の内側（#chat-messages より前）に置くこと"
    )
