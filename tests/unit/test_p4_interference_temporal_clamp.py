"""P4 — M1 interference 帯の境界 / 統合レビュー閾値、M4 時系列ボーナスのクランプ・場所フォールバック。"""

from __future__ import annotations

import json
from datetime import datetime
from unittest.mock import MagicMock

import pytest

from nous.domain.memory.entities import Memory
from nous.domain.memory.evolution_service import MemoryEvolutionService
from nous.domain.search.engine import SearchResult
from nous.domain.shared.result import Success
from nous.infrastructure.sqlite.memory_repo import SQLiteMemoryRepository

PERSONA = "test_p4"


def _mem(key: str, **kwargs) -> Memory:
    now = datetime(2026, 9, 19, 12, 0)
    return Memory(key=key, content="内容" * 10, created_at=now, updated_at=now, **kwargs)


class _FakeSearchEngine:
    def __init__(self, results: list[SearchResult]) -> None:
        self._results = results

    async def search(self, _query) -> Success:
        return Success(self._results)


def _service(results: list[SearchResult], repo: MagicMock) -> MemoryEvolutionService:
    return MemoryEvolutionService(
        search_engine_ref=[_FakeSearchEngine(results)],
        repo=repo,
        enricher=None,
        link_repo=None,
        contradiction_detector=None,
    )


def _result(key: str, score: float) -> SearchResult:
    return SearchResult(memory=_mem(key), score=score, source="semantic")


async def _run(results: list[SearchResult]) -> list[tuple]:
    repo = MagicMock()
    repo.update.return_value = Success(None)
    service = _service(results, repo)
    # 既存記憶のメタ更新を避けるため、類似探索の直後だけを見る（短い内容でも通す）。
    await service._evolve_related_memories(content="x" * 40, new_memory_key="new-key", persona=PERSONA)
    return repo.note_interference.call_args_list


# ===========================================================================
# M1 — 0.85–0.95 帯の境界
# ===========================================================================


@pytest.mark.asyncio
async def test_similarity_below_band_is_ignored() -> None:
    assert await _run([_result("old-1", 0.849)]) == []


@pytest.mark.asyncio
async def test_similarity_at_lower_bound_counts() -> None:
    calls = await _run([_result("old-1", 0.85)])
    assert calls == [(("old-1", "new-key", 0.85, PERSONA), {})]


@pytest.mark.asyncio
async def test_similarity_at_upper_bound_is_rewrite() -> None:
    """上限 0.95 ちょうどは「同じ記憶の書き直し」側（`[MIN, MAX)` の半開区間）。"""
    calls = await _run([_result("old-1", 0.95)])
    assert calls == []


@pytest.mark.asyncio
async def test_similarity_above_band_is_ignored() -> None:
    assert await _run([_result("old-1", 0.951)]) == []


# ===========================================================================
# M1 — count 3 の境目と統合レビュー（session_events）
# ===========================================================================


@pytest.fixture()
def repo(sqlite_conn) -> SQLiteMemoryRepository:
    return SQLiteMemoryRepository(sqlite_conn)


def _event_count(conn) -> int:
    row = (
        conn.get_memory_db()
        .execute("SELECT COUNT(*) FROM session_events WHERE event_type = 'memory.merge_review'")
        .fetchone()
    )
    return int(row[0])


def test_merge_review_queued_only_at_threshold(repo, sqlite_conn) -> None:
    repo.save(_mem("old-1"))

    assert repo.note_interference("old-1", "new-a", 0.9, PERSONA).value == 1
    assert _event_count(sqlite_conn) == 0
    assert repo.note_interference("old-1", "new-b", 0.9, PERSONA).value == 2
    assert _event_count(sqlite_conn) == 0
    assert repo.note_interference("old-1", "new-b", 0.9, PERSONA).value == 3
    assert _event_count(sqlite_conn) == 1

    row = (
        sqlite_conn.get_memory_db()
        .execute("SELECT persona, metadata_json FROM session_events WHERE event_type = 'memory.merge_review'")
        .fetchone()
    )
    assert row["persona"] == PERSONA
    meta = json.loads(row["metadata_json"])
    assert meta["keys"] == ["old-1", "new-b"]
    assert meta["interference_count"] == 3

    # 4 回目でも同じペアのレビューは重複しない。
    assert repo.note_interference("old-1", "new-b", 0.9, PERSONA).value == 4
    assert _event_count(sqlite_conn) == 1


# ===========================================================================
# M4 — ボーナスのクランプと場所フォールバック
# ===========================================================================


def test_temporal_bonus_is_clamped_to_initial_weight_cap(monkeypatch) -> None:
    from nous.domain.memory.link_service import MemoryLinkService

    monkeypatch.setattr(MemoryLinkService, "TEMPORAL_BONUS_SAME_DAY", 1.0)
    monkeypatch.setattr(MemoryLinkService, "TEMPORAL_BONUS_SAME_PLACE", 1.0)

    old = _mem("old-1", kind="episodic", episodic_time="2026-09-19T10:00", episodic_place="京都")
    new = _mem("new-key", kind="episodic", episodic_time="2026-09-19T18:00", episodic_place="京都")

    memory_repo = MagicMock()
    memory_repo.find_by_key.return_value = Success(old)
    link_repo = MagicMock()
    service = MemoryLinkService(link_repo, [None], memory_repo=memory_repo, coaccess_tracker=["old-1"])

    service._create_hebbian_links(new)

    strength = link_repo.upsert_link.call_args.kwargs["strength"]
    assert strength == pytest.approx(MemoryLinkService.MAX_INITIAL_STRENGTH)


def test_same_day_and_environment_gets_place_bonus() -> None:
    from nous.domain.memory.link_service import MemoryLinkService

    m1 = _mem("a", kind="episodic", episodic_time="2026-09-19T10:00", environment="京都")
    m2 = _mem("b", kind="episodic", episodic_time="2026-09-19T18:00", environment="京都")

    assert MemoryLinkService._temporal_bonus(m1, m2) == pytest.approx(0.3)
