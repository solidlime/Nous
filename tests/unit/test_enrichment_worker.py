"""EnrichmentWorker (REM-equivalent) unit tests.

- Cursor contract: only memories created after the previous cycle are
  processed (idempotent across cycles)
- Batch limit: LLM enrichment capped per cycle (brain_enrich_batch_limit)
- Novelty gate: vector-search only (no LLM); empty results = novel
  (max_cosine := 0.0); boost x brain_novelty_stability_multiplier + emit
- Emit convention: emit failure never breaks the loop
"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nous.application.use_cases import AppContextRegistry
from nous.application.workers.enrichment_worker import EnrichmentWorker
from nous.domain.memory import wiring_events
from nous.domain.memory.entities import Memory, MemoryStrength
from nous.domain.shared.result import Success
from nous.domain.shared.time_utils import get_now


@pytest.fixture(autouse=True)
def _clean_buffer():
    wiring_events.clear()
    yield
    wiring_events.clear()


def _memory(key: str, importance: float = 0.5, created_at=None) -> Memory:
    now = get_now().replace(tzinfo=None)
    return Memory(
        key=key,
        content=f"内容 {key}",
        created_at=created_at or now,
        updated_at=now,
        importance=importance,
    )


def _config() -> MagicMock:
    cfg = MagicMock()
    cfg.brain_enrich_interval_seconds = 60
    cfg.brain_enrich_batch_limit = 5
    cfg.brain_novelty_sim_threshold = 0.75
    cfg.brain_novelty_importance_threshold = 0.6
    cfg.brain_novelty_stability_multiplier = 2.0
    return cfg


def _ctx(memories: list[Memory]) -> MagicMock:
    ctx = MagicMock()
    ctx.memory_repo.find_all.return_value = MagicMock(is_ok=True, value=memories)
    ctx.memory_repo.get_strength.return_value = Success(MemoryStrength(memory_key=memories[0].key if memories else ""))
    ctx.memory_repo.save_strength.return_value = MagicMock(is_ok=True)
    ctx.vector_store = None
    ctx._enricher = None
    ctx.entity_service = None
    ctx.persona = "test_persona"
    return ctx


def _backdate(worker: EnrichmentWorker, memories: list[Memory]) -> None:
    """Make the cursor precede the given memories (as if created after start)."""
    oldest = min(m.created_at for m in memories)
    worker._cursor = oldest - timedelta(microseconds=1)


class TestEnrichmentWorker:
    def test_cursor_only_recent(self) -> None:
        """カーソル以降に作成された記憶のみ enrich 対象（2 周目は再処理しない）。"""
        old = _memory("old", created_at=get_now().replace(tzinfo=None) - timedelta(days=1))
        ctx = _ctx([old])
        worker = EnrichmentWorker(ctx, _config())

        new = _memory("new")
        new.created_at = worker._cursor + timedelta(microseconds=1)
        ctx.memory_repo.find_all.return_value.value.append(new)

        with patch("nous.application.workers.enrichment_worker.MemoryEnrichService") as svc_cls:
            svc = svc_cls.return_value
            svc.enrich_memory = AsyncMock()
            worker._run_cycle()
            assert svc.enrich_memory.await_count == 1
            assert svc.enrich_memory.await_args is not None
            # enrich_memory(memory, content, type_hints, key, importance)
            assert svc.enrich_memory.await_args.args[3] == "new"

            worker._run_cycle()
            assert svc.enrich_memory.await_count == 1, "2nd cycle must not re-process"

    def test_batch_limit(self) -> None:
        """1 周あたり brain_enrich_batch_limit(5) 件で LLM enrichment を打ち切り。"""
        memories = [_memory(f"k{i}") for i in range(8)]
        ctx = _ctx(memories)
        worker = EnrichmentWorker(ctx, _config())
        _backdate(worker, memories)

        with patch("nous.application.workers.enrichment_worker.MemoryEnrichService") as svc_cls:
            svc = svc_cls.return_value
            svc.enrich_memory = AsyncMock()
            worker._run_cycle()
            assert svc.enrich_memory.await_count == 5

    def test_novelty_gate_step(self) -> None:
        """新規記憶（類似なし／空検索結果）→ stability x2 と novelty_gate emit。"""
        ctx = _ctx([_memory("k1", importance=0.8)])
        worker = EnrichmentWorker(ctx, _config())
        _backdate(worker, ctx.memory_repo.find_all.return_value.value)

        strength = MemoryStrength(memory_key="k1")
        ctx.memory_repo.get_strength.return_value = Success(strength)

        worker._run_cycle()

        assert strength.stability == pytest.approx(2.0)
        ctx.memory_repo.save_strength.assert_called_once_with(strength)
        fires = [e for e in wiring_events.snapshot_after(0) if e["kind"] == "novelty_gate"]
        assert len(fires) == 1
        assert fires[0]["source"] == "k1"
        assert fires[0]["weight"] == pytest.approx(2.0)
        assert fires[0]["meta"]["memory_key"] == "k1"
        assert fires[0]["meta"]["max_cosine"] == 0.0

    def test_novelty_not_fires_when_similar(self) -> None:
        """類似度が閾値以上 → ブーストなし・emit なし。"""
        ctx = _ctx([_memory("k1", importance=0.8)])
        ctx.vector_store = MagicMock()
        ctx.vector_store.search = AsyncMock(return_value=Success([("old1", 0.9), ("old2", 0.5)]))
        worker = EnrichmentWorker(ctx, _config())
        _backdate(worker, ctx.memory_repo.find_all.return_value.value)

        worker._run_cycle()

        ctx.memory_repo.save_strength.assert_not_called()
        assert [e for e in wiring_events.snapshot_after(0) if e["kind"] == "novelty_gate"] == []

    def test_overflow_processed_next_cycle(self) -> None:
        """周上限を超えた溢れ分は 2 周目で処理される（永久取りこぼし防止）。"""
        memories = [_memory(f"k{i}") for i in range(8)]
        ctx = _ctx(memories)
        worker = EnrichmentWorker(ctx, _config())
        _backdate(worker, memories)

        with patch("nous.application.workers.enrichment_worker.MemoryEnrichService") as svc_cls:
            svc = svc_cls.return_value
            svc.enrich_memory = AsyncMock()
            worker._run_cycle()
            assert svc.enrich_memory.await_count == 5

            worker._run_cycle()
            assert svc.enrich_memory.await_count == 8
            keys = [c.args[3] for c in svc.enrich_memory.await_args_list]
            assert keys == [f"k{i}" for i in range(8)]

            worker._run_cycle()
            assert svc.enrich_memory.await_count == 8, "no third-cycle rework"

    def test_tie_created_at_processed_across_cycles(self) -> None:
        """同一 created_at の tie は processed-keys 集合で 1 回限り・後続周で処理。"""
        now = get_now().replace(tzinfo=None)
        memories = [_memory(f"t{i}", created_at=now) for i in range(3)]
        ctx = _ctx(memories)
        worker = EnrichmentWorker(ctx, _config())
        worker._batch_limit = 1
        _backdate(worker, memories)

        with patch("nous.application.workers.enrichment_worker.MemoryEnrichService") as svc_cls:
            svc = svc_cls.return_value
            svc.enrich_memory = AsyncMock()
            worker._run_cycle()
            worker._run_cycle()
            worker._run_cycle()
            assert svc.enrich_memory.await_count == 3
            assert {c.args[3] for c in svc.enrich_memory.await_args_list} == {"t0", "t1", "t2"}
            worker._run_cycle()
            assert svc.enrich_memory.await_count == 3, "tie must not re-enrich processed memories"

    def test_emits_follow_convention(self) -> None:
        """emit 失敗（raise）でもループは継続する。"""
        memories = [_memory("k1", importance=0.8), _memory("k2", importance=0.9)]
        ctx = _ctx(memories)
        ctx.memory_repo.get_strength.side_effect = lambda key: Success(MemoryStrength(memory_key=key))
        worker = EnrichmentWorker(ctx, _config())
        _backdate(worker, memories)

        with patch.object(wiring_events, "emit", side_effect=RuntimeError("boom")):
            worker._run_cycle()

        assert ctx.memory_repo.save_strength.call_count == 2, "loop must continue after emit failure"


class TestRegistryWiring:
    """use_cases.py 起動経路: enrichment 有効時に EnrichmentWorker を起動。"""

    def setup_method(self) -> None:
        AppContextRegistry._contexts.clear()
        AppContextRegistry._enrichment_workers.clear()

    def teardown_method(self) -> None:
        AppContextRegistry._contexts.clear()
        AppContextRegistry._enrichment_workers.clear()

    def _configure(self, tmp_path) -> None:
        settings = MagicMock()
        settings.persona_dir = str(tmp_path)
        (tmp_path / "p1").mkdir()
        AppContextRegistry.configure(settings)

    def _config_enabled(self) -> MagicMock:
        cfg = MagicMock()
        cfg.memory_enrichment_enabled = True
        cfg.brain_enrich_auto_run = True
        cfg.forgetting_enabled = False
        return cfg

    def test_started_when_enabled(self, tmp_path) -> None:
        self._configure(tmp_path)
        config = self._config_enabled()
        with (
            patch("nous.application.use_cases.AppContext") as mock_app_ctx,
            patch("nous.application.workers.enrichment_worker.EnrichmentWorker") as mock_cls,
        ):
            AppContextRegistry.get("p1", config)
            assert mock_cls.call_count == 1
            assert mock_cls.call_args.args[0] is mock_app_ctx.return_value

    def test_not_started_when_auto_run_off(self, tmp_path) -> None:
        self._configure(tmp_path)
        config = self._config_enabled()
        config.brain_enrich_auto_run = False
        with (
            patch("nous.application.use_cases.AppContext"),
            patch("nous.application.workers.enrichment_worker.EnrichmentWorker") as mock_cls,
        ):
            AppContextRegistry.get("p1", config)
            mock_cls.assert_not_called()
