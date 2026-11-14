"""プロジェクト文脈ビュー（kanban #8）の集計ロジック.

ルート自体は薄い HTTP ラッパなので、絞り込み・整形の関数を直接固定する。
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from nous.api.http.routers.project_context import (
    _item,
    _memories_with,
    _project_tag,
    _wiki_pages,
)
from nous.domain.memory.entities import Memory
from nous.domain.shared.result import Success
from nous.infrastructure.wiki.store import WikiStore

pytestmark = pytest.mark.unit


def _mem(key: str, tags: list[str], content: str = "c", created: int = 1) -> Memory:
    ts = datetime(2026, 1, created, tzinfo=UTC)
    return Memory(key=key, content=content, created_at=ts, updated_at=ts, tags=tags)


def _ctx(memories: list[Memory]) -> SimpleNamespace:
    return SimpleNamespace(memory_repo=SimpleNamespace(find_all=lambda: Success(memories)))


def test_project_tag_normalizes_case_and_space() -> None:
    assert _project_tag("  Nous ") == "project:nous"


def test_memories_with_filters_by_project_tag_newest_first() -> None:
    ctx = _ctx(
        [
            _mem("a", ["project:nous", "decision"], created=1),
            _mem("b", ["project:other"], created=2),
            _mem("c", ["project:nous"], created=3),
        ]
    )
    found = _memories_with(ctx, "project:nous")
    assert [m.key for m in found] == ["c", "a"]


def test_memories_with_failure_returns_empty() -> None:
    from nous.domain.shared.result import Failure

    ctx = SimpleNamespace(memory_repo=SimpleNamespace(find_all=lambda: Failure(Exception("boom"))))
    assert _memories_with(ctx, "project:nous") == []


def test_item_trims_content_and_carries_question_key() -> None:
    memory = _mem("k1", ["project:nous"], content="x" * 900)
    memory.source_context = "open-question:qkey:q:nous:abc"
    item = _item(memory)
    assert len(item["content"]) == 400
    assert item["question_key"] == "qkey:q:nous:abc"
    assert item["tags"] == ["project:nous"]


def test_wiki_pages_match_project_only(tmp_path) -> None:
    store = WikiStore(tmp_path, "p1")
    store.write_page("a", "A", "body a", project="Nous")
    store.write_page("b", "B", "body b", project="other")
    store.write_page("c", "C", "body c")  # project 無し

    pages = _wiki_pages(store, "nous")
    assert [p["slug"] for p in pages] == ["a"]
    assert pages[0]["title"] == "A"
