"""ExplorerConfig.max_tool_calls: 多段 curiosity 予算のデフォルトと clamp (1..10)。"""

from nous.config.settings import ExplorerConfig


def test_default_is_multi_step_budget():
    assert ExplorerConfig().max_tool_calls == 5


def test_single_source_cap_shared_with_introspection():
    """clamp は settings が単一ソース。introspection 側に cap リテラルを残さない。"""
    from nous.config.settings import MAX_TOOL_CALLS_CAP, clamp_max_tool_calls

    assert MAX_TOOL_CALLS_CAP == 10
    assert clamp_max_tool_calls(0) == 1
    assert clamp_max_tool_calls(99) == MAX_TOOL_CALLS_CAP

    from nous.application.chat import introspection

    assert getattr(introspection, "_CURIOSITY_MAX_CALLS_CAP", None) is None


def test_clamped_to_1_through_10():
    assert ExplorerConfig(max_tool_calls=0).max_tool_calls == 1
    assert ExplorerConfig(max_tool_calls=-3).max_tool_calls == 1
    assert ExplorerConfig(max_tool_calls=4).max_tool_calls == 4
    assert ExplorerConfig(max_tool_calls=99).max_tool_calls == 10
