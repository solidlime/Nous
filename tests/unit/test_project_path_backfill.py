"""audit H7: ``project_path:<abs>`` structured tag — backfill script + tag-search.

Covers the one-shot backfill script (``scripts/migrate_project_path_tags.py``)
and that the resulting tag is retrievable through the existing tag-search path.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from nous.domain.memory.entities import Memory
from nous.domain.search.engine import SearchEngine, SearchQuery
from nous.domain.shared.result import Success
from nous.domain.shared.time_utils import get_now
from nous.infrastructure.sqlite.memory_repo import SQLiteMemoryRepository

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "migrate_project_path_tags.py"


def _load_script() -> Any:
    spec = importlib.util.spec_from_file_location("migrate_project_path_tags", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


backfill_mod = _load_script()


def _mem(key: str, content: str, tags: list[str]) -> Memory:
    now = get_now()
    return Memory(key=key, content=content, created_at=now, updated_at=now, tags=list(tags))


class _FakeMemoryService:
    """Minimal in-memory stand-in for MemoryService (backfill uses 2 methods)."""

    def __init__(self, memories: list[Memory]) -> None:
        self._memories = memories
        self.updated: list[tuple[str, dict]] = []

    def get_by_tags(self, tags: list[str], include_consumed: bool = False) -> Success:
        return Success(list(self._memories))

    def update_memory(self, key: str, **updates: object) -> Success:
        self.updated.append((key, dict(updates)))
        for mem in self._memories:
            if mem.key == key:
                mem.tags = list(updates.get("tags") or mem.tags)  # type: ignore[arg-type]
        return Success(self._memories[0] if self._memories else None)


def _ctx(service: _FakeMemoryService) -> MagicMock:
    ctx = MagicMock()
    ctx.memory_service = service
    return ctx


class TestExtractProjectPath:
    def test_extracts_from_skill_line(self):
        content = "パス: /root/workspace/Nous。プロジェクト「Nous」を開始。目的: x"
        assert backfill_mod.extract_project_path(content) == "/root/workspace/Nous"

    def test_extracts_from_bulleted_line(self):
        assert backfill_mod.extract_project_path("- パス: /root/workspace/Nous") == "/root/workspace/Nous"

    def test_fullwidth_colon_and_trailing_slash(self):
        assert backfill_mod.extract_project_path("パス：/a/b/") == "/a/b"

    def test_no_path_returns_none(self):
        assert backfill_mod.extract_project_path("プロジェクトの説明だけ") is None
        assert backfill_mod.extract_project_path("") is None
        assert backfill_mod.extract_project_path(None) is None


class TestBackfillScript:
    def test_dry_run_does_not_write(self):
        mem = _mem("mem_1", "パス: /root/workspace/Nous。プロジェクト開始", ["project:nous"])
        service = _FakeMemoryService([mem])
        targets, added, skipped = backfill_mod.backfill_persona(_ctx(service), apply=False)
        assert (targets, added, skipped) == (1, 0, 0)
        assert service.updated == []
        assert mem.tags == ["project:nous"]

    def test_apply_adds_tag_and_is_idempotent(self):
        mem = _mem("mem_1", "パス: /root/workspace/Nous。プロジェクト開始", ["project:nous"])
        service = _FakeMemoryService([mem])
        ctx = _ctx(service)

        targets, added, skipped = backfill_mod.backfill_persona(ctx, apply=True)
        assert (targets, added, skipped) == (1, 1, 0)
        assert mem.tags == ["project:nous", "project_path:/root/workspace/Nous"]

        # 2 回目は既にタグがあるため追加しない（冪等）
        targets, added, skipped = backfill_mod.backfill_persona(ctx, apply=True)
        assert (targets, added, skipped) == (0, 0, 1)
        assert len(service.updated) == 1

    def test_skips_memory_without_absolute_path(self):
        mem = _mem("mem_2", "プロジェクト「x」の概要のみ", ["project:x"])
        service = _FakeMemoryService([mem])
        targets, added, skipped = backfill_mod.backfill_persona(_ctx(service), apply=True)
        assert (targets, added, skipped) == (0, 0, 1)
        assert service.updated == []


class _KeywordAdapter:
    """Minimal KeywordSearchStrategy adapter over SQLiteMemoryRepository."""

    def __init__(self, repo: SQLiteMemoryRepository) -> None:
        self._repo = repo

    def search(self, query: str, limit: int = 10, date_from=None, date_to=None, tags=None):
        return self._repo.search_keyword(query, limit, date_from=date_from, date_to=date_to, tags=tags)


class TestProjectPathTagSearch:
    """project_path タグが既存のタグ検索経路（query 空 + tags）でヒットする。"""

    @pytest.mark.asyncio
    async def test_project_path_tag_is_searchable(self, sqlite_conn):
        repo = SQLiteMemoryRepository(sqlite_conn)
        now = get_now()
        tagged = Memory(
            key="mem_pp",
            content="パス: /root/workspace/Nous。プロジェクト開始",
            created_at=now,
            updated_at=now,
            tags=["project:nous", "project_path:/root/workspace/Nous"],
        )
        other = Memory(
            key="mem_other",
            content="別プロジェクト",
            created_at=now,
            updated_at=now,
            tags=["project:other", "project_path:/root/workspace/Other"],
        )
        assert repo.save(tagged).is_ok
        assert repo.save(other).is_ok

        engine = SearchEngine(keyword_search=_KeywordAdapter(repo), memory_repo=repo)
        result = await engine.search(
            SearchQuery(text="", mode="keyword", tags=["project_path:/root/workspace/Nous"], top_k=5)
        )

        assert result.is_ok
        keys = [r.memory.key for r in result.value]
        assert "mem_pp" in keys
        assert "mem_other" not in keys
