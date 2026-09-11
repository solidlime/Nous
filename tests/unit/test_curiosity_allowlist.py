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
