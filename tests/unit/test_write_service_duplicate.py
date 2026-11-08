"""MemoryWriteService の重複検知 — archived は「忘却済み」なので重複扱いしない。"""

from __future__ import annotations

from dataclasses import replace
from unittest.mock import MagicMock

from nous.domain.memory.entities import Memory
from nous.domain.memory.write_service import MemoryWriteService
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
