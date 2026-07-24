from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

from nous.application.workers.decay_worker import DecayWorker
from nous.domain.memory.entities import MemoryStrength
from nous.domain.shared.time_utils import get_now


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

    def test_start_stop(self) -> None:
        """start/stop がスレッドを制御できる"""
        ctx = _make_ctx([])
        worker = DecayWorker(ctx, interval_seconds=9999)
        worker.start()
        assert worker._running is True
        worker.stop()
        assert worker._running is False
