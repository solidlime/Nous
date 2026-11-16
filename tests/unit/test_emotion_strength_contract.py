"""感情の適用先契約（audit H5）と brain_emotion_gain_k 廃止（H4）。

- 感情強度は作成時スナップショットのみ。永続 strength/stability を変えない。
- emotion_peak は廃止（書き込まれない）。
- 検索時は RankPolicy の salience 項としてのみ効く。
- brain_emotion_gain_k は設定・コードから削除済み。
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest

from nous.domain.memory.entities import Memory
from nous.domain.memory.query_service import resolve_brain_config
from nous.domain.memory.service import MemoryService
from nous.domain.search.engine import SearchEngine, SearchQuery, SearchResult
from nous.domain.search.policy import RankPolicy
from nous.domain.session_config import SessionConfig
from nous.domain.shared.time_utils import get_now
from nous.infrastructure.sqlite.connection import SQLiteConnection
from nous.infrastructure.sqlite.memory_repo import SQLiteMemoryRepository

if TYPE_CHECKING:
    from datetime import datetime


def _mem(key: str, intensity: float, created_at: datetime | None = None) -> Memory:
    now = created_at if created_at is not None else get_now()
    return Memory(
        key=key,
        content="記憶",
        created_at=now,
        updated_at=now,
        emotion="joy",
        emotion_intensity=intensity,
    )


@pytest.mark.asyncio
async def test_high_emotion_does_not_inflate_persistent_strength(tmp_path) -> None:
    """感情強度 1.0 の記憶でも strength/stability は初期値のまま、emotion_peak も 0。"""
    conn = SQLiteConnection(str(tmp_path), "test_persona")
    conn.initialize_schema()
    svc = MemoryService(SQLiteMemoryRepository(conn))

    result = await svc.create_memory(content="とても嬉しい記憶", emotion="joy", emotion_intensity=1.0)
    assert result.is_ok

    row = (
        conn.get_memory_db()
        .execute(
            "SELECT strength, stability, emotion_peak FROM memory_strength WHERE memory_key = ?",
            (result.value.key,),
        )
        .fetchone()
    )
    assert tuple(row) == (1.0, 1.0, 0.0)


@pytest.mark.asyncio
async def test_rank_policy_emotion_salience_boosts_high_intensity() -> None:
    """RankPolicy の salience 項で高強度の記憶が同条件の低強度より上位になる。"""
    fixed = get_now()
    low = SearchResult(memory=_mem("low", 0.0, fixed), score=0.0, source="semantic", cosine=0.5)
    high = SearchResult(memory=_mem("high", 1.0, fixed), score=0.0, source="semantic", cosine=0.5)
    engine = SearchEngine(keyword_search=MagicMock())

    ranked = await engine._apply_rank_policy([low, high], SearchQuery(text="q", top_k=5, rank_policy=RankPolicy()))

    assert [r.memory.key for r in ranked] == ["high", "low"]
    assert ranked[0].score - ranked[1].score == pytest.approx(RankPolicy().emotion_salience_weight)


@pytest.mark.asyncio
async def test_rank_policy_emotion_salience_zero_is_backward_compatible() -> None:
    """salience 重み 0 では感情強度が順位・スコアに影響しない。"""
    fixed = get_now()
    low = SearchResult(memory=_mem("low", 0.0, fixed), score=0.0, source="semantic", cosine=0.5)
    high = SearchResult(memory=_mem("high", 1.0, fixed), score=0.0, source="semantic", cosine=0.5)
    engine = SearchEngine(keyword_search=MagicMock())

    ranked = await engine._apply_rank_policy(
        [low, high],
        SearchQuery(text="q", top_k=5, rank_policy=RankPolicy(emotion_salience_weight=0.0)),
    )

    assert [r.memory.key for r in ranked] == ["low", "high"]
    assert ranked[0].score == pytest.approx(ranked[1].score)


def test_h5_stability_clamp_runs_once(tmp_path) -> None:
    """H5: 感情で膨らんだ旧 stability を初回サイクルで 1 回だけ clamp する（LTM は除外）。"""
    from nous.infrastructure.sqlite.migrations import run_migrations

    conn = SQLiteConnection(str(tmp_path), "test_persona")
    conn.initialize_schema()
    db = conn.get_memory_db()
    db.execute(
        "INSERT INTO memories (key, content, created_at, updated_at) VALUES ('a', 'x', '2020-01-01', '2020-01-01'), ('b', 'y', '2020-01-01', '2020-01-01')"
    )
    db.execute(
        "INSERT INTO memory_strength (memory_key, strength, stability, is_ltm) VALUES ('a', 1.0, 1.5, 0), ('b', 1.0, 2.5, 1)"
    )
    db.commit()
    # initialize_schema が既に v13 を適用済みなので、v13 未適用の旧 DB を再現する
    db.execute("DELETE FROM _migration_version WHERE version = 13")
    db.commit()

    run_migrations(db, "test_persona")
    rows = db.execute("SELECT memory_key, stability FROM memory_strength ORDER BY memory_key").fetchall()
    assert [tuple(r) for r in rows] == [("a", 1.0), ("b", 2.5)]

    # 2 回目以降は走らない（one-shot）
    db.execute("UPDATE memory_strength SET stability = 1.8 WHERE memory_key = 'a'")
    db.commit()
    run_migrations(db, "test_persona")
    assert db.execute("SELECT stability FROM memory_strength WHERE memory_key = 'a'").fetchone()["stability"] == 1.8


def test_brain_emotion_gain_k_removed_from_defaults_and_config() -> None:
    """H4: 死にノブ brain_emotion_gain_k はデフォルトにも設定スキーマにも無い。"""
    assert "brain_emotion_gain_k" not in resolve_brain_config(object())
    assert "brain_emotion_gain_k" not in SessionConfig.model_fields
