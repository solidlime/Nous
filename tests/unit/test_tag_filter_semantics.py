"""Tag filtering is an EXACT subset match — a prefix-style tag never matches.

Audit L6 found the workflow skills teaching a wrong mental model ("``project:``
is a substring, so it matches ``project:<slug>``"). The engine's post-filter
requires every requested tag to be present verbatim, so a prefix tag silently
returns nothing while ``repo.get_by_tags`` (SQL ``LIKE '%"tag"%'``) does return
rows — a combination that makes a "run query, then filter the hits" fallback look
like it works when it cannot.

Guards the fix: session-start step 2b reads the tag distribution from
``memory_stats`` instead of relying on prefix matching.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from nous.domain.memory.entities import Memory
from nous.domain.search.engine import SearchEngine, SearchQuery
from nous.domain.shared.result import Success
from tests.unit.test_search_engine import _make_keyword_strategy


def _mem(key: str, tags: list[str]) -> Memory:
    now = datetime.now(UTC)
    return Memory(key=key, content=f"content {key}", created_at=now, updated_at=now, tags=tags)


async def _search(memory_repo: MagicMock, tags: list[str]) -> list[str]:
    engine = SearchEngine(keyword_search=_make_keyword_strategy(), memory_repo=memory_repo)
    result = await engine.search(SearchQuery(text="", mode="keyword", tags=tags, top_k=10))
    assert isinstance(result, Success), result
    return [r.memory.key for r in result.value]


@pytest.mark.asyncio
async def test_prefix_style_tag_returns_nothing():
    mems = [
        _mem("m1", ["project:nous", "project_path:/root/workspace/Nous"]),
        _mem("m2", ["project:nous"]),
        _mem("m3", ["project_overview", "project:nous"]),
    ]
    memory_repo = MagicMock()
    memory_repo.get_by_tags.return_value = Success(mems)

    # The repository does its own LIKE-based lookup and would return all three...
    assert [m.key for m in memory_repo.get_by_tags(["project:"]).value] == ["m1", "m2", "m3"]

    # ...but no prefix tag survives the engine's exact post-filter.
    assert await _search(memory_repo, ["project:"]) == []

    # Exact tags are what the workflow must use.
    assert await _search(memory_repo, ["project:nous"]) == ["m1", "m2", "m3"]
    assert await _search(memory_repo, ["project_overview"]) == ["m3"]
