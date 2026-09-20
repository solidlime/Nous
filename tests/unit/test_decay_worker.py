from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from nous.application.workers.decay_worker import DecayWorker
from nous.domain.memory import wiring_events
from nous.domain.memory.entities import Memory, MemoryStrength
from nous.domain.session_config import SessionConfig
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
        """recall × strength が min_strength 未満の場合はスキップする"""
        # use_old_decay=True: last_decay=2020-01-01 → elapsed ≈ 58000+ hours
        # FSRS recall ≈ 0.018 → 0.3 × 0.018 ≈ 0.005 < min_strength=0.01 → skip
        s = _make_strength("mem_001", strength=0.3, use_old_decay=True)
        ctx = _make_ctx([s], min_strength=0.01)

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
    key: str,
    emotion_intensity: float = 0.0,
    kind: str = "semantic",
    source_type: str = "user_stated",
    importance: float = 0.5,
) -> Memory:
    now = get_now().replace(tzinfo=None)
    return Memory(
        key=key,
        content=f"内容 {key}",
        created_at=now,
        updated_at=now,
        importance=importance,
        emotion_intensity=emotion_intensity,
        kind=kind,
        source_type=source_type,
    )


class TestDecayWorkerBrain:
    def test_stability_replay_fire(self) -> None:
        """decay 保存成功後に stability 型 replay_fire が発火する（weight=更新後 strength）。"""
        # 3 日前の last_decay → recall ≈ 0.13 → strength 0.8→0.10 (delta > 0.05)
        s = _make_strength("mem_001")
        s.last_decay = get_now() - timedelta(days=3)
        ctx = _make_ctx([s])

        worker = DecayWorker(ctx, interval_seconds=3600)
        worker._decay_cycle()

        fires = [e for e in wiring_events.snapshot_after(0) if e["kind"] == "replay_fire"]
        assert len(fires) == 1
        assert fires[0]["source"] == "mem_001"
        assert fires[0]["weight"] == pytest.approx(s.strength)

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

    def test_subtle_decay_does_not_fire(self) -> None:
        """微細な減衰（delta ≤ 0.05）では replay_fire を発火しない。"""
        strength = _make_strength("subtle", strength=0.36)
        strength.last_recall = get_now()  # recency を効かせて score を固定（delta≈0.035）
        ctx = _make_ctx([strength])

        worker = DecayWorker(ctx, interval_seconds=3600)
        worker._decay_cycle()

        assert ctx.memory_repo.save_strength.call_count == 1
        assert [e for e in wiring_events.snapshot_after(0) if e["kind"] == "replay_fire"] == []

    def test_promotion_fires_replay(self) -> None:
        """STM→LTM 昇格時は delta が小さくても replay_fire を発火する。"""
        strength = _make_strength("promo", strength=0.85)
        strength.recall_count = 3
        strength.last_recall = get_now()
        strength.last_utility = get_now()
        ctx = _make_ctx([strength])
        ctx.memory_repo.find_all.return_value = MagicMock(
            is_ok=True,
            value=[_make_memory("promo", importance=0.9)],
        )

        worker = DecayWorker(ctx, interval_seconds=3600)
        worker._decay_cycle()

        assert strength.is_ltm is True
        fires = [e for e in wiring_events.snapshot_after(0) if e["kind"] == "replay_fire"]
        assert len(fires) == 1
        assert fires[0]["source"] == "promo"
        assert fires[0]["weight"] == pytest.approx(strength.strength)


class TestDecayWorkerReflection:
    """案件2: periodic ReflectionEngine の DecayWorker 配線。"""

    @staticmethod
    def _worker(engine, ctx, llm_provider):
        return DecayWorker(
            ctx,
            interval_seconds=3600,
            reflection_engine=engine,
            llm_provider=llm_provider,
        )

    def test_reflect_runs_at_interval_boundary(self) -> None:
        """REFLECTION_INTERVAL 到達時に reflect が呼ばれ、それまでは呼ばれない。"""
        engine = MagicMock()
        engine.reflect = AsyncMock(return_value=[])
        ctx = _make_ctx([_make_strength("mem_001")])
        ctx.persona = "test_char"
        worker = self._worker(engine, ctx, llm_provider=MagicMock())

        for _ in range(DecayWorker.REFLECTION_INTERVAL - 1):
            worker._run_cycle()
        engine.reflect.assert_not_called()

        worker._run_cycle()  # interval 到達 → reflect 呼び出し
        engine.reflect.assert_called_once()
        kwargs = engine.reflect.call_args.kwargs
        assert kwargs["persona"] == "test_char"
        assert kwargs["memory_service"] is ctx.memory_service
        assert kwargs["llm"] is not None

        # 次の interval でも再度呼ばれる
        for _ in range(DecayWorker.REFLECTION_INTERVAL):
            worker._run_cycle()
        assert engine.reflect.call_count == 2

    def test_reflect_interval_from_config(self) -> None:
        """config.reflection_interval_cycles が実行間隔を上書きする（既定 24）。"""
        engine = MagicMock()
        engine.reflect = AsyncMock(return_value=[])
        ctx = _make_ctx([_make_strength("mem_001")])
        ctx.persona = "test_char"
        cfg = MagicMock()
        cfg.reflection_interval_cycles = 2
        cfg.forgetting_min_strength = 0.01
        worker = DecayWorker(
            ctx,
            interval_seconds=3600,
            reflection_engine=engine,
            llm_provider=MagicMock(),
            config=cfg,
        )

        worker._run_cycle()
        engine.reflect.assert_not_called()
        worker._run_cycle()  # 2サイクル目 → interval=2 で発火
        engine.reflect.assert_called_once()

    def test_reflection_disabled_skips(self) -> None:
        """config.reflection_enabled=False なら reflect を呼ばない。"""
        engine = MagicMock()
        engine.reflect = AsyncMock(return_value=[])
        ctx = _make_ctx([])
        ctx.persona = "test_char"
        cfg = SessionConfig(reflection_enabled=False)
        worker = DecayWorker(ctx, interval_seconds=3600, reflection_engine=engine, llm_provider=MagicMock(), config=cfg)

        worker._maybe_run_reflection()

        engine.reflect.assert_not_called()

    def test_reflection_min_interval_gate_skips_second_run(self) -> None:
        """reflection_min_interval_hours 未満の再実行はスキップ（二重ゲート）。"""
        engine = MagicMock()
        engine.reflect = AsyncMock(return_value=[])
        ctx = _make_ctx([])
        ctx.persona = "test_char"
        cfg = SessionConfig(reflection_min_interval_hours=5.0)
        worker = DecayWorker(ctx, interval_seconds=3600, reflection_engine=engine, llm_provider=MagicMock(), config=cfg)

        worker._maybe_run_reflection()  # 初回は実行
        engine.reflect.assert_called_once()
        worker._maybe_run_reflection()  # 経過 ≈ 0h < 5h → skip
        engine.reflect.assert_called_once()

    def test_reflection_min_interval_zero_disables_gate(self) -> None:
        """reflection_min_interval_hours が 0 以下ならゲートなし（現行挙動）。"""
        engine = MagicMock()
        engine.reflect = AsyncMock(return_value=[])
        ctx = _make_ctx([])
        ctx.persona = "test_char"
        cfg = SessionConfig(reflection_min_interval_hours=0.0)
        worker = DecayWorker(ctx, interval_seconds=3600, reflection_engine=engine, llm_provider=MagicMock(), config=cfg)

        worker._maybe_run_reflection()
        worker._maybe_run_reflection()

        assert engine.reflect.call_count == 2

    def test_llm_none_is_noop(self) -> None:
        """llm_provider=None なら reflect を呼ばず例外も出さない。"""
        engine = MagicMock()
        engine.reflect = AsyncMock(return_value=[])
        ctx = _make_ctx([])
        ctx.persona = "test_char"
        worker = self._worker(engine, ctx, llm_provider=None)

        worker._maybe_run_reflection()
        engine.reflect.assert_not_called()

    def test_engine_none_is_noop(self) -> None:
        """reflection_engine=None でも例外を出さない。"""
        ctx = _make_ctx([])
        ctx.persona = "test_char"
        worker = self._worker(None, ctx, llm_provider=MagicMock())

        worker._maybe_run_reflection()  # no-op

    def test_reflection_event_recorded_on_success(self) -> None:
        """洞察生成成功時は session_events に brain.reflection を記録する。"""
        engine = MagicMock()
        engine.reflect = AsyncMock(return_value=[{"insight": "i", "evidence_keys": [], "confidence": 0.8}])
        ctx = _make_ctx([_make_strength("mem_001")])
        ctx.persona = "test_char"
        repo = MagicMock()
        ctx._session_event_repo = repo
        worker = self._worker(engine, ctx, llm_provider=MagicMock())

        worker._maybe_run_reflection()

        repo.insert.assert_called_once()
        event = repo.insert.call_args.args[0]
        assert event.event_type == "brain.reflection"
        assert event.persona == "test_char"
        assert event.metadata == {"insights": 1}


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
