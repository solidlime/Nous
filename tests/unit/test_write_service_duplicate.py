"""MemoryWriteService の重複検知 — archived は「忘却済み」なので重複扱いしない。"""

from __future__ import annotations

from dataclasses import replace
from unittest.mock import MagicMock

from nous.domain.memory.entities import Memory
from nous.domain.memory.write_service import MemoryWriteService
from nous.domain.search.engine import SearchResult
from nous.domain.shared.result import Success
from nous.domain.shared.time_utils import get_now

CONTENT = "同じ内容の発話"


def _service(lifecycle: str) -> MemoryWriteService:
    now = get_now()
    memory = Memory(
        key="k-old",
        content=CONTENT,
        created_at=now,
        updated_at=now,
        importance=0.5,
        kind="semantic",
        source_type="user_stated",
        lifecycle_status=lifecycle,
        tags=[],
    )
    repo = MagicMock()
    repo.find_by_content_exact.return_value = Success(replace(memory))
    return MemoryWriteService(repo=repo, search_engine_ref=[])


async def test_archived_exact_match_is_not_a_duplicate() -> None:
    """archived は重複として弾かない（想起も再学習もできない知識喪失を避ける）。"""
    assert await _service("archived")._check_duplicate(CONTENT) is None


async def test_active_exact_match_is_a_duplicate() -> None:
    assert await _service("active")._check_duplicate(CONTENT) is not None


class _FakeEngine:
    """semantic スコア 1 件だけ返す検索エンジン（しきい値境界の検証用）。"""

    def __init__(self, score: float) -> None:
        now = get_now()
        self._result = SearchResult(
            memory=Memory(
                key="k-sim",
                content=CONTENT,
                created_at=now,
                updated_at=now,
                importance=0.5,
                kind="semantic",
                source_type="user_stated",
                lifecycle_status="active",
                tags=[],
            ),
            score=score,
            source="semantic",
        )

    async def search(self, _query) -> Success:
        return Success([self._result])


def _semantic_service(score: float) -> MemoryWriteService:
    repo = MagicMock()
    repo.find_by_content_exact.return_value = Success(None)
    return MemoryWriteService(repo=repo, search_engine_ref=[_FakeEngine(score)])


async def test_semantic_score_below_085_is_not_a_duplicate() -> None:
    """D4-1: 0.75→0.85 統一。0.84 は素通し（旧 0.75 では重複扱いだった帯）。"""
    assert await _semantic_service(0.84)._check_duplicate(CONTENT) is None


async def test_semantic_score_at_or_above_085_is_a_duplicate() -> None:
    assert await _semantic_service(0.86)._check_duplicate(CONTENT) is not None
