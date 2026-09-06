"""Retrieval-induced forgetting (RIF) tests — SearchEngine competitor suppression.

契約（Anderson 1994 / 脳シミュレーション設計 3.4）:
- 競合群 = 最終 recall 結果から除外された上位 K(=5) 件の候補
- 効果: strength *= (1 - ρ)、recall（search 呼び出し）あたり 1 回
- 床: min_strength = 0.005、importance 不変、emit なし
- recalled された記憶は不変
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from nous.domain.memory.entities import Memory, MemoryStrength
from nous.domain.search.engine import SearchEngine, SearchQuery
from nous.domain.shared.result import Success

RHO = 0.05  # brain_rif_suppression_rho のデフォルト
FLOOR = 0.005  # min_strength（nous/infrastructure/config/settings.py:91）


def _mem(key: str, emotion: str = "neutral") -> Memory:
    now = datetime.now(UTC)
    return Memory(
        key=key,
        content=key,
        created_at=now,
        updated_at=now,
        importance=0.5,
        emotion=emotion,
        tags=[],
    )


class _StrengthRepo:
    """get_strength / save_strength を備えるテスト用 memory_repo。"""

    def __init__(self, strengths: dict[str, MemoryStrength]):
        self.strengths = strengths

    def get_strength(self, key: str):
        return Success(self.strengths.get(key))

    def save_strength(self, strength: MemoryStrength):
        self.strengths[strength.memory_key] = strength
        return Success(None)


def _make_engine(pairs: list[tuple[Memory, float]], repo) -> SearchEngine:
    strat = MagicMock()
    strat.search.return_value = Success(pairs)
    return SearchEngine(keyword_search=strat, memory_repo=repo)


def _strength(key: str, value: float) -> MemoryStrength:
    return MemoryStrength(memory_key=key, strength=value, stability=10.0)


class TestRifSuppression:
    @pytest.mark.asyncio
    async def test_rif_suppresses_competitors(self):
        """recalled されなかった競合のみ *(1-ρ)、recalled は不変、importance 不変."""
        pairs = [
            (_mem("r1", emotion="joy"), 0.9),
            (_mem("r2", emotion="joy"), 0.8),
            (_mem("c1"), 0.7),
            (_mem("c2"), 0.6),
        ]
        repo = _StrengthRepo({k: _strength(k, 0.8) for k in ("r1", "r2", "c1", "c2")})
        engine = _make_engine(pairs, repo)

        result = await engine.search(SearchQuery(text="rif-basic", mode="keyword", emotion="joy", top_k=4))
        assert result.is_ok
        assert {r.memory.key for r in result.value} == {"r1", "r2"}

        # recalled された記憶は不変
        assert repo.strengths["r1"].strength == pytest.approx(0.8)
        assert repo.strengths["r2"].strength == pytest.approx(0.8)
        # 競合のみ *(1 - ρ)
        assert repo.strengths["c1"].strength == pytest.approx(0.8 * (1 - RHO))
        assert repo.strengths["c2"].strength == pytest.approx(0.8 * (1 - RHO))
        # importance 不変（Memory エンティティ側は一切更新されない）
        assert pairs[2][0].importance == 0.5

    @pytest.mark.asyncio
    async def test_rif_respects_floor(self):
        """ρ 適用後も strength ≥ 0.005。床未満には落ちない。"""
        pairs = [(_mem("kept", emotion="joy"), 0.9), (_mem("low"), 0.5)]
        repo = _StrengthRepo({"kept": _strength("kept", 0.8), "low": _strength("low", FLOOR)})
        engine = _make_engine(pairs, repo)

        result = await engine.search(SearchQuery(text="rif-floor", mode="keyword", emotion="joy", top_k=2))
        assert result.is_ok

        assert repo.strengths["kept"].strength == pytest.approx(0.8)
        assert repo.strengths["low"].strength == pytest.approx(FLOOR)

    @pytest.mark.asyncio
    async def test_rif_caps_at_five_competitors(self):
        """競合群は上位 5 件まで——6 番目以降は抑制されない。"""
        pairs = [(_mem("r0", emotion="joy"), 0.99)]
        pairs += [(_mem(f"c{i}"), 0.9 - 0.01 * i) for i in range(7)]
        repo = _StrengthRepo({m.key: _strength(m.key, 0.8) for m, _ in pairs})
        engine = _make_engine(pairs, repo)

        result = await engine.search(SearchQuery(text="rif-cap", mode="keyword", emotion="joy", top_k=8))
        assert result.is_ok

        for i in range(5):
            assert repo.strengths[f"c{i}"].strength == pytest.approx(0.8 * (1 - RHO))
        for i in (5, 6):
            assert repo.strengths[f"c{i}"].strength == pytest.approx(0.8)

    @pytest.mark.asyncio
    async def test_rif_noop_without_memory_repo(self):
        """memory_repo なしでも検索は壊れない。"""
        pairs = [(_mem("a"), 0.9), (_mem("b"), 0.5)]
        engine = _make_engine(pairs, repo=None)
        result = await engine.search(SearchQuery(text="rif-norepo", mode="keyword", top_k=2))
        assert result.is_ok
        assert len(result.value) == 2
