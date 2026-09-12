from nous.application.chat.introspection import _curiosity_tool_allowed


def test_mutating_tools_excluded():
    for name in (
        "update_context", "item_equip", "item_add", "item_remove", "item_update",
        "get_context", "memory_create", "memory_update", "memory_delete", "goal_manage",
        "create_memory", "delete_item", "set_state", "add_item",
    ):
        assert not _curiosity_tool_allowed(name), name


def test_readonly_tools_allowed():
    for name in ("memory_search", "memory_read", "memory_stats", "web_search", "fetch_url"):
        assert _curiosity_tool_allowed(name), name


def test_read_markers_are_token_exact_not_substring():
    # "spREADsheet" の誤マッチを防ぐ（トークン完全一致）
    assert not _curiosity_tool_allowed("spreadsheet_write")
    # 現行許可集合は維持
    for name in ("memory_search", "memory_read", "memory_stats", "web_search", "fetch_url", "list_skills", "invoke_skill"):
        assert _curiosity_tool_allowed(name), name


def test_future_write_tools_denied():
    # 正の allowlist: save_*/write_* 等が増えても自動的に除外される
    for name in ("save_memory", "write_file", "put_state", "post_message", "upload_doc"):
        assert not _curiosity_tool_allowed(name), name
