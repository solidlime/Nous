from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from nous.application.workers.decay_worker import DecayWorker
from nous.domain.memory import wiring_events
from nous.domain.memory.entities import Memory, MemoryStrength
from nous.domain.shared.time_utils import get_now


@pytest.fixture(autouse=True)
def _clean_wiring_buffer():
    wiring_events.clear()
    yield
    wiring_events.clear()


def _make_strength(key: str, strength: float = 0.8, use_old_decay: bool = False) -> MemoryStrength:
    s = MemoryStrength(memory_key=key)
    s.strength = strength
    # Old date → elapsed ≈ years → compute_recall ≈ 0 (below min_strength)
    # Recent date → elapsed ≈ 0 → compute_recall ≈ 1.0 (above min_strength)
    s.last_decay = datetime(2020, 1, 1, tzinfo=UTC) if use_old_decay else get_now()
    return s


def _make_ctx(strengths: list[MemoryStrength], min_strength: float = 0.01) -> MagicMock:
    ctx = MagicMock()
    ctx.memory_repo.get_all_strengths.return_value = MagicMock(is_ok=True, value=strengths)
    ctx.memory_repo.save_strength.return_value = MagicMock(is_ok=True)
    ctx.settings.forgetting.min_strength = min_strength
    return ctx


def _make_config(min_strength: float = 0.01) -> MagicMock:
    cfg = MagicMock()
    cfg.forgetting_min_strength = min_strength
    return cfg


class TestDecayWorker:
    def test_decay_cycle_applies_decay(self) -> None:
        """_decay_cycle() は全 strength レコードに decay を適用する"""
        # recent last_decay → elapsed ≈ 0 → compute_recall ≈ 1.0 (above min_strength)
        strengths = [_make_strength("mem_001"), _make_strength("mem_002")]
        ctx = _make_ctx(strengths)

        worker = DecayWorker(ctx, interval_seconds=3600)
        worker._decay_cycle()

        assert ctx.memory_repo.save_strength.call_count == 2

    def test_decay_cycle_skips_below_min_strength(self) -> None:
        """compute_recall が min_strength 未満の場合はスキップする"""
        # use_old_decay=True: last_decay=2020-01-01 → elapsed ≈ 50000+ hours
        # FSRS: (1 + 19*50000/24)^(-0.5) ≈ 0.005 < min_strength=0.01 → skip
        strengths = [_make_strength("mem_001", use_old_decay=True)]
        ctx = _make_ctx(strengths, min_strength=0.01)

        worker = DecayWorker(ctx, interval_seconds=3600)
        worker._decay_cycle()

        ctx.memory_repo.save_strength.assert_not_called()

    def test_decay_cycle_handles_repo_error(self) -> None:
        """get_all_strengths が失敗しても例外を投げない"""
        ctx = MagicMock()
        ctx.memory_repo.get_all_strengths.return_value = MagicMock(is_ok=False, error="DB error")

        worker = DecayWorker(ctx, interval_seconds=3600)
        worker._decay_cycle()

    def test_stop_joins_within_timeout(self) -> None:
        """stop() は Event を set し、スレッドが timeout 内に終了する"""
        import time

        ctx = _make_ctx([])
        worker = DecayWorker(ctx, interval_seconds=9999)
        worker.start()
        assert worker._thread is not None
        assert worker._thread.is_alive()

        start = time.monotonic()
        worker.stop(timeout=5)
        elapsed = time.monotonic() - start

        assert worker._stop_event.is_set()
        assert not worker._thread.is_alive(), "worker thread must exit within timeout"
        assert elapsed < 5, "stop() must not block for the full interval (Event.wait, not time.sleep)"


def _make_memory(
    key: str, emotion_intensity: float = 0.0, kind: str = "semantic", source_type: str = "user_stated"
) -> Memory:
    now = get_now().replace(tzinfo=None)
    return Memory(
        key=key,
        content=f"内容 {key}",
        created_at=now,
        updated_at=now,
        emotion_intensity=emotion_intensity,
        kind=kind,
        source_type=source_type,
    )


class TestDecayWorkerBrain:
    def test_stability_replay_fire(self) -> None:
        """decay 保存成功後に stability 型 replay_fire が発火する（weight=更新後 strength）。"""
        strengths = [_make_strength("mem_001")]
        ctx = _make_ctx(strengths)

        worker = DecayWorker(ctx, interval_seconds=3600)
        worker._decay_cycle()

        fires = [e for e in wiring_events.snapshot_after(0) if e["kind"] == "replay_fire"]
        assert len(fires) == 1
        assert fires[0]["source"] == "mem_001"
        assert fires[0]["weight"] == pytest.approx(strengths[0].strength)

    def test_gist_resists_decay(self) -> None:
        """consolidated semantic（gist ノード）は減衰対象から除外される。"""
        strength = _make_strength("g1")
        ctx = _make_ctx([strength])
        ctx.memory_repo.find_all.return_value = MagicMock(
            is_ok=True, value=[_make_memory("g1", kind="semantic", source_type="consolidated")]
        )

        worker = DecayWorker(ctx, interval_seconds=3600)
        worker._decay_cycle()

        ctx.memory_repo.save_strength.assert_not_called()
        assert strength.strength == pytest.approx(0.8)

    def test_emotion_eases_decay(self) -> None:
        """感情強度が高い記憶ほど減衰が緩やか（1/(1 + 0.5*i) の緩和係数）。"""
        s0 = _make_strength("e0", strength=0.8)
        s1 = _make_strength("e1", strength=0.8)
        ctx = _make_ctx([s0, s1])
        ctx.memory_repo.find_all.return_value = MagicMock(
            is_ok=True,
            value=[_make_memory("e0"), _make_memory("e1", emotion_intensity=1.0)],
        )

        worker = DecayWorker(ctx, interval_seconds=3600)
        worker._decay_cycle()

        assert ctx.memory_repo.save_strength.call_count == 2
        assert s1.strength > s0.strength


class TestConsolidationWorkerEventStop:
    def test_stop_joins_within_timeout(self) -> None:
        """ConsolidationWorker も Event.wait 化されている（stop→join が timeout 内に返る）"""
        import time

        from nous.application.workers.consolidation_worker import ConsolidationWorker

        worker = ConsolidationWorker(settings=MagicMock())
        worker.interval_seconds = 9999
        worker.start()
        assert worker._thread is not None

        start = time.monotonic()
        worker.stop(timeout=5)
        elapsed = time.monotonic() - start

        assert worker._stop_event.is_set()
        assert not worker._thread.is_alive()
        assert elapsed < 5
