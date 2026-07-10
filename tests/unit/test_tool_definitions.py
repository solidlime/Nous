"""Schema integrity tests for ToolDefinition definitions.

These tests validate structural invariants of MEMORY_TOOLS
to catch regressions during refactoring (e.g. promise_manage/goal_manage).
"""

from __future__ import annotations

from unittest.mock import MagicMock

from nous.application.chat.tools.definitions import (
    CONDITIONAL_TOOLS,
    CORE_ALWAYS_TOOLS,
    MEMORY_TOOLS,
    get_filtered_tools,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_VALID_JSON_SCHEMA_TYPES = frozenset(
    {
        "string",
        "number",
        "integer",
        "boolean",
        "array",
        "object",
        "null",
    }
)


def _all_tools():
    """Shorthand for iterating over every defined tool."""
    yield from MEMORY_TOOLS


# ---------------------------------------------------------------------------
# Basic existence & description
# ---------------------------------------------------------------------------


def test_all_tools_have_name_and_description():
    """Every ToolDefinition has a non-empty name and description."""
    for td in _all_tools():
        assert td.name, f"Tool missing name: {td}"
        assert td.description, f"Tool {td.name} has empty description"


def test_all_tools_have_input_schema_with_type_object():
    """Every input_schema is a dict with type == 'object'."""
    for td in _all_tools():
        schema = td.input_schema
        assert isinstance(schema, dict), f"{td.name}: input_schema not a dict"
        assert schema.get("type") == "object", (
            f"{td.name}: input_schema.type is '{schema.get('type')}', expected 'object'"
        )


# ---------------------------------------------------------------------------
# Required keys integrity
# ---------------------------------------------------------------------------


def test_all_required_keys_exist_in_properties():
    """All keys listed in 'required' must exist in 'properties'."""
    for td in _all_tools():
        props = td.input_schema.get("properties", {})
        for req_key in td.input_schema.get("required", []):
            assert req_key in props, f"{td.name}: required key '{req_key}' not found in properties"


def test_all_enums_are_non_empty():
    """Every 'enum' constraint across all properties is non-empty."""
    for td in _all_tools():
        for prop_name, prop in td.input_schema.get("properties", {}).items():
            if "enum" in prop:
                assert len(prop["enum"]) > 0, f"{td.name}.{prop_name}: enum is empty"


# ---------------------------------------------------------------------------
# Uniqueness
# ---------------------------------------------------------------------------


def test_no_duplicate_tool_names():
    """No duplicate tool names across MEMORY_TOOLS."""
    names = [td.name for td in _all_tools()]
    assert len(names) == len(set(names)), f"Duplicate names: {[n for n in names if names.count(n) > 1]}"


# ---------------------------------------------------------------------------
# Post-#1 regression guards
#
# These tests validate that #1 changes (remove promise_manage, add scope
# to goal_manage) were correctly applied.  They will FAIL before #1 is
# implemented -- that is EXPECTED behaviour.
# ---------------------------------------------------------------------------


def test_promise_manage_removed():
    """promise_manage does not exist in any tool list (post-#1)."""
    names = [td.name for td in _all_tools()]
    assert "promise_manage" not in names, "promise_manage should have been removed in #1"


def test_scope_enum_values():
    """goal_manage.scope enum equals ['self', 'interpersonal'] (post-#1)."""
    goal_td = next(td for td in MEMORY_TOOLS if td.name == "goal_manage")
    assert goal_td.input_schema["properties"]["scope"]["enum"] == [
        "self",
        "interpersonal",
    ], "goal_manage scope enum should be ['self', 'interpersonal'] after #1"


# ---------------------------------------------------------------------------
# JSON Schema type validity
# ---------------------------------------------------------------------------


def test_property_types_are_valid_json_schema_types():
    """All property 'type' values are valid JSON Schema types.

    Checks top-level properties and nested items-type schemas.
    Properties without a 'type' key are skipped (some are just enum-only).
    """
    for td in _all_tools():
        for prop_name, prop in td.input_schema.get("properties", {}).items():
            if "type" not in prop:
                continue
            assert prop["type"] in _VALID_JSON_SCHEMA_TYPES, f"{td.name}.{prop_name}: invalid type '{prop['type']}'"
            # Recurse into array items
            if prop["type"] == "array" and isinstance(prop.get("items"), dict):
                item_type = prop["items"].get("type")
                if item_type:
                    assert item_type in _VALID_JSON_SCHEMA_TYPES, (
                        f"{td.name}.{prop_name}.items: invalid type '{item_type}'"
                    )


# ---------------------------------------------------------------------------
# P22: CORE_ALWAYS_TOOLS integrity
# ---------------------------------------------------------------------------


def test_core_always_tools_all_exist_in_memory_tools():
    """Every CORE_ALWAYS_TOOLS name must exist in MEMORY_TOOLS.

    If a new core tool is added, it must first be defined in MEMORY_TOOLS.
    """
    memory_names = {td.name for td in MEMORY_TOOLS}
    missing = CORE_ALWAYS_TOOLS - memory_names
    assert not missing, (
        f"CORE_ALWAYS_TOOLS missing from MEMORY_TOOLS: {missing}"
    )


def test_get_filtered_tools_always_includes_core():
    """get_filtered_tools が CORE_ALWAYS_TOOLS を絶対に除外しないことを保証する。"""
    mock_config = MagicMock()
    mock_config.dynamic_tool_selection = True

    result = get_filtered_tools(mock_config)
    result_names = {td.name for td in result}

    missing = CORE_ALWAYS_TOOLS - result_names
    assert not missing, (
        f"get_filtered_tools がコアツールを除外: {missing}"
    )


def test_get_filtered_tools_dynamic_off_returns_all():
    """dynamic_tool_selection=False で全ツールが返る。"""
    mock_config = MagicMock()
    mock_config.dynamic_tool_selection = False

    result = get_filtered_tools(mock_config)
    assert len(result) == len(MEMORY_TOOLS)
    result_names = {td.name for td in result}
    expected_names = {td.name for td in MEMORY_TOOLS}
    assert result_names == expected_names


def test_get_filtered_tools_dynamic_on_returns_all_currently():
    """dynamic_tool_selection=True でも現状は全ツールが返る（将来の制限基盤）。"""
    mock_config = MagicMock()
    mock_config.dynamic_tool_selection = True

    result = get_filtered_tools(mock_config)
    assert len(result) == len(MEMORY_TOOLS)
    result_names = {td.name for td in result}
    expected_names = {td.name for td in MEMORY_TOOLS}
    assert result_names == expected_names


def test_conditional_tools_are_subset_of_all_builtin_tools():
    """CONDITIONAL_TOOLS のキーは全て MEMORY_TOOLS に存在する。"""
    all_names = {td.name for td in MEMORY_TOOLS}
    unknown = set(CONDITIONAL_TOOLS) - all_names
    assert not unknown, (
        f"CONDITIONAL_TOOLS のキーが MEMORY_TOOLS に存在しない: {unknown}"
    )


def test_conditional_tools_not_in_core():
    """CONDITIONAL_TOOLS のキーは CORE_ALWAYS_TOOLS と重複しない。"""
    overlap = set(CONDITIONAL_TOOLS) & CORE_ALWAYS_TOOLS
    assert not overlap, (
        f"CONDITIONAL_TOOLS が CORE_ALWAYS_TOOLS と重複: {overlap}"
    )
