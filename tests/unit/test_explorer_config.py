"""ExplorerConfig.max_tool_calls: 多段 curiosity 予算のデフォルトと clamp (1..10)。"""

from nous.config.settings import ExplorerConfig


def test_default_is_multi_step_budget():
    assert ExplorerConfig().max_tool_calls == 5


def test_clamped_to_1_through_10():
    assert ExplorerConfig(max_tool_calls=0).max_tool_calls == 1
    assert ExplorerConfig(max_tool_calls=-3).max_tool_calls == 1
    assert ExplorerConfig(max_tool_calls=4).max_tool_calls == 4
    assert ExplorerConfig(max_tool_calls=99).max_tool_calls == 10
