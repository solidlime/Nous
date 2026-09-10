"""ExplorerConfig のデフォルトと env オーバーライド。"""

from nous.config.settings import Settings


def test_explorer_defaults():
    s = Settings()
    assert s.explorer.enabled is True
    assert s.explorer.max_tool_calls == 1


def test_explorer_enabled_override():
    s = Settings(explorer={"enabled": True, "max_tool_calls": 2})
    assert s.explorer.enabled is True
    assert s.explorer.max_tool_calls == 2
