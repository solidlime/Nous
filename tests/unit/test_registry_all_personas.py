"""``AppContextRegistry.all_personas()`` — ディスク上の persona ∪ 生成済み (kanban #85).

再起動後まだ誰も触っていない persona の予定が永久に発火しないバグの回帰テスト。
"""

from __future__ import annotations

import types
from unittest.mock import MagicMock

import pytest

from nous.application.use_cases import AppContextRegistry


@pytest.fixture()
def persona_root(monkeypatch, tmp_path):
    monkeypatch.setattr(AppContextRegistry, "_settings", types.SimpleNamespace(persona_dir=str(tmp_path)))
    monkeypatch.setattr(AppContextRegistry, "_contexts", {})
    monkeypatch.setattr(AppContextRegistry, "_deleting", set())
    return tmp_path


def test_disk_persona_is_listed_without_a_context(persona_root):
    (persona_root / "herta").mkdir()

    assert AppContextRegistry.personas() == []
    assert AppContextRegistry.all_personas() == ["herta"]


def test_union_with_live_contexts_is_sorted(persona_root):
    (persona_root / "b").mkdir()
    AppContextRegistry._contexts["a"] = MagicMock()

    assert AppContextRegistry.all_personas() == ["a", "b"]


def test_deleting_and_hidden_directories_are_skipped(persona_root):
    (persona_root / "live").mkdir()
    (persona_root / "gone").mkdir()
    (persona_root / ".cache").mkdir()
    (persona_root / "not-a-persona.txt").write_text("x")
    AppContextRegistry._deleting.add("gone")

    assert AppContextRegistry.all_personas() == ["live"]
