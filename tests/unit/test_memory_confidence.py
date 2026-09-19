"""audit C4 — confidence dynamics + provenance modality (v4.0, P4).

Confidence is adjusted on contradiction (×0.5) and corroboration (+0.1, cap 1.0).
It is never used as a ranking weight.
Modality is derived from ``source_type`` (single source of truth).
"""

from __future__ import annotations

import pytest

from nous.domain.memory.contradiction import ContradictionResult, ContradictionType
from nous.domain.memory.entities import MODALITY_BY_SOURCE_TYPE, VALID_MODALITIES, Memory
from nous.domain.memory.evolution_service import (
    CONTRADICTED_CONFIDENCE_FACTOR,
    CORROBORATION_CONFIDENCE_DELTA,
    CORROBORATION_SIMILARITY_MIN,
    MemoryEvolutionService,
)
from nous.domain.search.engine import SearchResult
from nous.domain.shared.result import Success
from nous.domain.shared.time_utils import get_now
from nous.infrastructure.sqlite.connection import SQLiteConnection
from nous.infrastructure.sqlite.memory_repo import SQLiteMemoryRepository

PERSONA = "test_confidence"

OLD_CONTENT = "ユーザーは毎朝コーヒーを飲むのが日課であり、紅茶は苦手だと記録されている。"
NEW_CONTENT = "ユーザーは毎朝コーヒーを飲む習慣をやめ、今は紅茶だけを飲んでいるという記録。"


@pytest.fixture()
def memory_repo(tmp_path):
    conn = SQLiteConnection(data_dir=str(tmp_path), persona=PERSONA)
    conn.initialize_schema()
    yield SQLiteMemoryRepository(conn)
    conn.close()


class _FakeSearchEngine:
    def __init__(self, memories: list[Memory], score: float):
        self._memories = memories
        self._score = score

    async def search(self, query):
        return Success([SearchResult(memory=m, score=self._score, source="semantic") for m in self._memories])


class _FakeEnricher:
    def __init__(self, result: ContradictionResult):
        self._result = result

    async def classify_contradiction(self, new_content: str, existing_memories: list[dict]):
        return self._result


def _result(ctype: ContradictionType, key: str) -> ContradictionResult:
    return ContradictionResult(type=ctype, existing_memory_key=key, explanation="", updated_fields=None)


async def _evolve(memory_repo, old: Memory, new: Memory, ctype: ContradictionType, score: float) -> None:
    service = MemoryEvolutionService(
        search_engine_ref=[_FakeSearchEngine([old], score)],
        repo=memory_repo,
        enricher=_FakeEnricher(_result(ctype, old.key)),
        link_repo=None,
        contradiction_detector=None,
    )
    await service._evolve_related_memories(content=new.content, new_memory_key=new.key)


def _pair(confidence: float = 1.0) -> tuple[Memory, Memory]:
    now = get_now()
    old = Memory(key="mem_old", content=OLD_CONTENT, created_at=now, updated_at=now, confidence=confidence)
    new = Memory(key="mem_new", content=NEW_CONTENT, created_at=now, updated_at=now)
    return old, new


class TestProvenanceModality:
    def test_modality_derives_from_source_type(self):
        now = get_now()
        for source_type, expected in MODALITY_BY_SOURCE_TYPE.items():
            mem = Memory(key="k", content="c", created_at=now, updated_at=now, source_type=source_type)
            assert mem.modality == expected
            assert mem.modality in VALID_MODALITIES

    def test_every_valid_source_type_has_a_modality(self):
        """新しい source_type を足したら modality 対応も足す必要がある（回帰ガード）."""
        from nous.domain.memory.entities import VALID_SOURCE_TYPES

        assert set(MODALITY_BY_SOURCE_TYPE) == VALID_SOURCE_TYPES


class TestConfidenceDynamics:
    @pytest.mark.asyncio
    async def test_contradiction_halves_confidence(self, memory_repo):
        old, new = _pair(confidence=1.0)
        memory_repo.save(old)
        memory_repo.save(new)

        await _evolve(memory_repo, old, new, ContradictionType.CONTRADICTORY, score=0.9)

        assert memory_repo.find_by_key("mem_old").value.confidence == pytest.approx(
            1.0 * CONTRADICTED_CONFIDENCE_FACTOR
        )

    @pytest.mark.asyncio
    async def test_corroboration_raises_confidence(self, memory_repo):
        old, new = _pair(confidence=0.6)
        memory_repo.save(old)
        memory_repo.save(new)

        await _evolve(memory_repo, old, new, ContradictionType.EXTENDABLE, score=CORROBORATION_SIMILARITY_MIN)

        assert memory_repo.find_by_key("mem_old").value.confidence == pytest.approx(
            0.6 + CORROBORATION_CONFIDENCE_DELTA
        )

    @pytest.mark.asyncio
    async def test_corroboration_caps_at_one(self, memory_repo):
        old, new = _pair(confidence=0.95)
        memory_repo.save(old)
        memory_repo.save(new)

        await _evolve(memory_repo, old, new, ContradictionType.EXTENDABLE, score=0.95)

        assert memory_repo.find_by_key("mem_old").value.confidence == 1.0

    @pytest.mark.asyncio
    async def test_low_similarity_does_not_corroborate(self, memory_repo):
        """0.9 未満の再記憶は corroboration とみなさない."""
        old, new = _pair(confidence=0.6)
        memory_repo.save(old)
        memory_repo.save(new)

        await _evolve(memory_repo, old, new, ContradictionType.EXTENDABLE, score=CORROBORATION_SIMILARITY_MIN - 0.05)

        assert memory_repo.find_by_key("mem_old").value.confidence == pytest.approx(0.6)

    @pytest.mark.asyncio
    async def test_independent_leaves_confidence_untouched(self, memory_repo):
        old, new = _pair(confidence=0.6)
        memory_repo.save(old)
        memory_repo.save(new)

        await _evolve(memory_repo, old, new, ContradictionType.INDEPENDENT, score=0.95)

        assert memory_repo.find_by_key("mem_old").value.confidence == pytest.approx(0.6)
