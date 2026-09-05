"""Bitemporal contradiction chain tests (F2 lane).

CONTRADICTORY は tombstone せず、旧記憶の validity window を閉じて
``superseded_by`` で新記憶へ連鎖させる。旧事実は残る。
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from nous.domain.memory.contradiction import ContradictionResult, ContradictionType
from nous.domain.memory.entities import Memory
from nous.domain.memory.evolution_service import MemoryEvolutionService
from nous.domain.search.engine import SearchEngine, SearchQuery, SearchResult
from nous.domain.shared.result import Success
from nous.domain.shared.time_utils import get_now
from nous.infrastructure.sqlite.connection import SQLiteConnection
from nous.infrastructure.sqlite.memory_repo import SQLiteMemoryRepository

PERSONA = "test_bitemporal"


@pytest.fixture()
def sqlite_conn(tmp_path):
    conn = SQLiteConnection(data_dir=str(tmp_path), persona=PERSONA)
    conn.initialize_schema()
    yield conn
    conn.close()


@pytest.fixture()
def memory_repo(sqlite_conn: SQLiteConnection):
    return SQLiteMemoryRepository(sqlite_conn)


def _make_memory(key: str, content: str, valid_from: datetime) -> Memory:
    now = get_now()
    return Memory(key=key, content=content, created_at=now, updated_at=now, valid_from=valid_from)


class _FakeSearchEngine:
    def __init__(self, memories: list[Memory]):
        self._memories = memories

    async def search(self, query):
        return Success([SearchResult(memory=m, score=0.9, source="semantic") for m in self._memories])


class _FakeEnricher:
    def __init__(self, result: ContradictionResult):
        self._result = result

    async def classify_contradiction(self, new_content: str, existing_memories: list[dict]):
        return self._result


class _FakeKeyword:
    """Stub keyword strategy returning fixed memories regardless of query."""

    def __init__(self, memories: list[Memory]):
        self._memories = memories

    def search(
        self,
        query: str,
        limit: int = 10,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        tags: list[str] | None = None,
    ):
        return Success([(m, 1.0) for m in self._memories[:limit]])


def _contradictory(key: str) -> ContradictionResult:
    return ContradictionResult(
        type=ContradictionType.CONTRADICTORY,
        existing_memory_key=key,
        explanation="明確に矛盾する",
        updated_fields=None,
    )


async def _evolve(memory_repo, old: Memory, new: Memory) -> None:
    service = MemoryEvolutionService(
        search_engine_ref=[_FakeSearchEngine([old])],
        repo=memory_repo,
        enricher=_FakeEnricher(_contradictory(old.key)),
        link_repo=None,
        contradiction_detector=None,
    )
    await service._evolve_related_memories(content=new.content, new_memory_key=new.key)


OLD_CONTENT = "私は毎朝コーヒーを飲むのが日課であり、紅茶は苦手だと感じている。"
NEW_CONTENT = "私は毎朝紅茶を飲むようになり、コーヒーはもう飲まなくなったという記録。"
NEW2_CONTENT = "私は毎朝白湯だけを飲む生活に切り替え、紅茶もやめたという最新の記録。"


class TestBitemporalChain:
    @pytest.mark.asyncio
    async def test_contradiction_closes_window_and_chains(self, memory_repo):
        """矛盾1連鎖: 旧 valid_until=新 valid_from、旧 superseded_by=新 key、旧事実は残る"""
        t0 = get_now() - timedelta(hours=2)
        t1 = get_now() - timedelta(hours=1)
        old = _make_memory("mem_old", OLD_CONTENT, t0)
        new = _make_memory("mem_new", NEW_CONTENT, t1)
        memory_repo.save(old)
        memory_repo.save(new)

        await _evolve(memory_repo, old, new)

        got_old = memory_repo.find_by_key("mem_old").value
        assert got_old is not None
        assert got_old.content == OLD_CONTENT
        assert got_old.lifecycle_status != "tombstoned"
        assert got_old.valid_until == memory_repo.find_by_key("mem_new").value.valid_from
        assert got_old.superseded_by == "mem_new"

    @pytest.mark.asyncio
    async def test_contradiction_two_chain(self, memory_repo):
        """矛盾2連鎖: mem1 -> mem2 -> mem3 の superseded_by 連鎖"""
        t0 = get_now() - timedelta(hours=3)
        t1 = get_now() - timedelta(hours=2)
        t2 = get_now() - timedelta(hours=1)
        m1 = _make_memory("mem_1", OLD_CONTENT, t0)
        m2 = _make_memory("mem_2", NEW_CONTENT, t1)
        m3 = _make_memory("mem_3", NEW2_CONTENT, t2)
        memory_repo.save(m1)
        memory_repo.save(m2)
        memory_repo.save(m3)

        await _evolve(memory_repo, m1, m2)
        await _evolve(memory_repo, m2, m3)

        got1 = memory_repo.find_by_key("mem_1").value
        got2 = memory_repo.find_by_key("mem_2").value
        got3 = memory_repo.find_by_key("mem_3").value
        assert got1.superseded_by == "mem_2"
        assert got1.valid_until == got2.valid_from
        assert got2.superseded_by == "mem_3"
        assert got2.valid_until == got3.valid_from
        assert got3.valid_until is None
        assert got3.superseded_by is None
        # 履歴保持: 旧記憶の version スナップショットが残る
        assert len(memory_repo.get_versions("mem_1").value) >= 1
        assert len(memory_repo.get_versions("mem_2").value) >= 1

    @pytest.mark.asyncio
    async def test_recall_past_returns_old_only(self, memory_repo):
        """過去 valid_at では旧のみが想起される"""
        t0 = get_now() - timedelta(hours=3)
        t1 = get_now() - timedelta(hours=2)
        old = _make_memory("mem_old", OLD_CONTENT, t0)
        new = _make_memory("mem_new", NEW_CONTENT, t1)
        memory_repo.save(old)
        memory_repo.save(new)
        await _evolve(memory_repo, old, new)

        stored = [memory_repo.find_by_key("mem_old").value, memory_repo.find_by_key("mem_new").value]
        engine = SearchEngine(keyword_search=_FakeKeyword(stored))
        result = await engine.search(
            SearchQuery(text="朝の飲み物", mode="keyword", valid_at=t0 + timedelta(minutes=30))
        )
        assert isinstance(result, Success)
        assert [r.memory.key for r in result.value] == ["mem_old"]

    @pytest.mark.asyncio
    async def test_recall_now_returns_new_only(self, memory_repo):
        """現在では新のみが想起される（旧は valid_until 期限切れ）"""
        t0 = get_now() - timedelta(hours=3)
        t1 = get_now() - timedelta(hours=2)
        old = _make_memory("mem_old", OLD_CONTENT, t0)
        new = _make_memory("mem_new", NEW_CONTENT, t1)
        memory_repo.save(old)
        memory_repo.save(new)
        await _evolve(memory_repo, old, new)

        stored = [memory_repo.find_by_key("mem_old").value, memory_repo.find_by_key("mem_new").value]
        engine = SearchEngine(keyword_search=_FakeKeyword(stored))
        result = await engine.search(SearchQuery(text="朝の飲み物", mode="keyword", valid_at=get_now()))
        assert isinstance(result, Success)
        assert [r.memory.key for r in result.value] == ["mem_new"]
        # valid_at 省略時も現在として新のみ
        default = await engine.search(SearchQuery(text="朝の飲み物", mode="keyword"))
        assert isinstance(default, Success)
        assert [r.memory.key for r in default.value] == ["mem_new"]

    @pytest.mark.asyncio
    async def test_recall_excludes_tombstoned(self, memory_repo):
        """tombstone 済みは想起から除外される（ユーザー明示削除専用）"""
        t0 = get_now() - timedelta(hours=1)
        mem = _make_memory("mem_gone", "これはユーザーが明示的に削除した朝の飲み物の記録です。", t0)
        memory_repo.save(mem)
        memory_repo.tombstone("mem_gone")

        stored = [memory_repo.find_by_key("mem_gone").value]
        engine = SearchEngine(keyword_search=_FakeKeyword(stored))
        result = await engine.search(SearchQuery(text="朝の飲み物", mode="keyword", valid_at=get_now()))
        assert isinstance(result, Success)
        assert result.value == []
