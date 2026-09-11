"""Spec F (2026-09-12): extractor skip rules for fields the chat LLM updated directly."""

from __future__ import annotations

from nous.application.chat.memory_extractor import _context_update_skips


def test_update_context_fields_skip():
    log = [{"name": "update_context", "input": {"emotion": "joy", "mental_state": "眠い", "user_name": "x"}}]
    se, sb, st, su, _ = _context_update_skips(log)
    assert (se, st, su) == (True, True, True) and sb is False


def test_item_tool_skips_inventory_but_search_does_not():
    se, sb, st, su, si = _context_update_skips([{"name": "item_equip", "input": {"slot": "top"}}])
    assert (se, sb, st, su, si) == (False, False, False, False, True)
    assert _context_update_skips([{"name": "item_search", "input": {}}])[-1] is False


def test_no_log_all_false():
    assert _context_update_skips(None) == (False, False, False, False, False)
