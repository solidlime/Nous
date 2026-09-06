"""EnrichmentWorker (idle-gated queue drain) unit tests.

- Idle gate: drains only after brain_idle_after_seconds without activity
- Min batch: waits when fewer than brain_min_batch_size items are pending
- Forced drain: brain_max_defer_seconds-exceeded items drain even when active
- event_repo None: treated as not-idle, except defer-exceeded items
- has_processed guard: processed keys are never re-enriched
- Novelty gate: vector-search only (no LLM); empty results = novel
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
from nous.infrastructure.sqlite.enrichment_queue_repo import PendingItem


@pytest.fixture(autouse=True)
def _clean_buffer():
    wiring_events.clear()
    yield
    wiring_events.clear()


def _memory(key: str, importance: float = 0.5) -> Memory:
    now = get_now()
    return Memory(
        key=key,
        content=f"内容 {key}",
        created_at=now.replace(tzinfo=None),
        updated_at=now.replace(tzinfo=None),
        importance=importance,
    )


def _config(**overrides) -> MagicMock:
    cfg = MagicMock()
    cfg.brain_enrich_interval_seconds = 60
    cfg.brain_enrich_batch_limit = 5
    cfg.brain_novelty_sim_threshold = 0.75
    cfg.brain_novelty_importance_threshold = 0.6
    cfg.brain_novelty_stability_multiplier = 2.0
    cfg.brain_idle_after_seconds = 120
    cfg.brain_min_batch_size = 3
    cfg.brain_max_defer_seconds = 3600
    for name, value in overrides.items():
        setattr(cfg, name, value)
    return cfg


def _ctx() -> MagicMock:
    ctx = MagicMock()
    ctx.persona = "test_persona"
    ctx.memory_repo.save_strength.return_value = MagicMock(is_ok=True)
    ctx.vector_store = None
    ctx._enricher = None
    ctx.entity_service = None
    ctx._session_event_repo = None
    ctx.enrichment_queue = MagicMock()
    return ctx


def _wire_queue(ctx, keys: list[str], *, enqueued_at=None, processed: set[str] | None = None):
    """Point ctx.enrichment_queue at a mock holding the given pending keys."""
    now = get_now()
    q = ctx.enrichment_queue
    q.pending_keys.return_value = [
        PendingItem(memory_key=k, enqueued_at=enqueued_at if enqueued_at is not None else now) for k in keys
    ]
    processed = processed or set()
    q.has_processed.side_effect = lambda key: key in processed
    return q


def _idle_ctx(ctx, idle_seconds: float) -> MagicMock:
    """Session event repo reporting last activity idle_seconds ago."""
    ctx._session_event_repo = MagicMock()
    ctx._session_event_repo.last_activity_at.return_value = get_now() - timedelta(seconds=idle_seconds)
    return ctx


class TestIdleGatedDrain:
    def _worker_with_repo(self, ctx, keys: list[str], **cfg_overrides):
        memories = [_memory(k) for k in keys]
        ctx.memory_repo.find_by_key.side_effect = lambda key: Success(next(m for m in memories if m.key == key))
        return EnrichmentWorker(ctx, _config(**cfg_overrides)), memories

    def test_drains_when_idle(self) -> None:
        ctx = _ctx()
        _idle_ctx(ctx, idle_seconds=600)
        _wire_queue(ctx, ["k1", "k2", "k3"])
        worker, _ = self._worker_with_repo(ctx, ["k1", "k2", "k3"])

        with patch("nous.application.workers.enrichment_worker.MemoryEnrichService") as svc_cls:
            svc = svc_cls.return_value
            svc.enrich_memory = AsyncMock()
            worker._run_cycle()
            assert svc.enrich_memory.await_count == 3

        enriched = ctx.memory_repo.find_by_key.call_args_list
        assert [c.args[0] for c in enriched] == ["k1", "k2", "k3"]
        assert ctx.enrichment_queue.mark_processed.call_count == 3

    def test_waits_while_active(self) -> None:
        ctx = _ctx()
        _idle_ctx(ctx, idle_seconds=5)
        _wire_queue(ctx, ["k1", "k2", "k3"])
        worker, _ = self._worker_with_repo(ctx, ["k1", "k2", "k3"])

        worker._run_cycle()

        ctx.enrichment_queue.mark_processed.assert_not_called()
        assert ctx.memory_repo.find_by_key.call_count == 0

    def test_waits_below_min_batch(self) -> None:
        ctx = _ctx()
        _idle_ctx(ctx, idle_seconds=600)
        _wire_queue(ctx, ["k1", "k2"])
        worker, _ = self._worker_with_repo(ctx, ["k1", "k2"])

        worker._run_cycle()

        ctx.enrichment_queue.mark_processed.assert_not_called()
        assert ctx.memory_repo.find_by_key.call_count == 0

    def test_forced_drain_on_defer_exceeded(self) -> None:
        """Old pending items drain even while the persona is active."""
        ctx = _ctx()
        _idle_ctx(ctx, idle_seconds=0)
        _wire_queue(ctx, ["k1"], enqueued_at=get_now() - timedelta(hours=2))
        worker, _ = self._worker_with_repo(ctx, ["k1"])

        with patch("nous.application.workers.enrichment_worker.MemoryEnrichService") as svc_cls:
            svc = svc_cls.return_value
            svc.enrich_memory = AsyncMock()
            worker._run_cycle()
            assert svc.enrich_memory.await_count == 1

        ctx.enrichment_queue.mark_processed.assert_called_once_with("k1")

    def test_event_repo_none_skips_unless_defer_exceeded(self) -> None:
        """No session_event_repo → not idle → skip; defer forces the drain."""
        ctx = _ctx()
        assert ctx._session_event_repo is None
        _wire_queue(ctx, ["k1", "k2"])
        worker, _ = self._worker_with_repo(ctx, ["k1", "k2"])

        worker._run_cycle()
        ctx.enrichment_queue.mark_processed.assert_not_called()

        _wire_queue(ctx, ["k1", "k2"], enqueued_at=get_now() - timedelta(hours=2))
        with patch("nous.application.workers.enrichment_worker.MemoryEnrichService") as svc_cls:
            svc = svc_cls.return_value
            svc.enrich_memory = AsyncMock()
            worker._run_cycle()
            assert svc.enrich_memory.await_count == 2

    def test_processed_keys_not_reenriched(self) -> None:
        """has_processed keys are marked without LLM enrichment."""
        ctx = _ctx()
        _idle_ctx(ctx, idle_seconds=600)
        # defer-exceeded so the min-batch gate doesn't mask the drain
        _wire_queue(ctx, ["k1", "k2"], enqueued_at=get_now() - timedelta(hours=2), processed={"k1"})
        worker, _ = self._worker_with_repo(ctx, ["k1", "k2"])

        with patch("nous.application.workers.enrichment_worker.MemoryEnrichService") as svc_cls:
            svc = svc_cls.return_value
            svc.enrich_memory = AsyncMock()
            worker._run_cycle()
            assert svc.enrich_memory.await_count == 1
            assert svc.enrich_memory.await_args is not None
            assert svc.enrich_memory.await_args.args[3] == "k2"

        # both keys marked (k1 flushed from pending, k2 after processing)
        assert ctx.enrichment_queue.mark_processed.call_count == 2

    def test_find_by_key_failure_does_not_break_drain(self) -> None:
        """A missing memory still gets marked so the queue keeps flowing."""
        ctx = _ctx()
        _idle_ctx(ctx, idle_seconds=600)
        _wire_queue(ctx, ["k1", "k2", "k3"])
        ctx.memory_repo.find_by_key.side_effect = lambda key: (
            Success(_memory(key)) if key != "k2" else MagicMock(is_ok=False, value=None)
        )
        worker = EnrichmentWorker(ctx, _config())

        with patch("nous.application.workers.enrichment_worker.MemoryEnrichService") as svc_cls:
            svc = svc_cls.return_value
            svc.enrich_memory = AsyncMock()
            worker._run_cycle()
            assert svc.enrich_memory.await_count == 2

        assert ctx.enrichment_queue.mark_processed.call_count == 3


class TestNoveltyGate:
    def test_novelty_gate_step(self) -> None:
        """新規記憶（類似なし／空検索結果）→ stability x2 と novelty_gate emit。"""
        ctx = _ctx()
        _idle_ctx(ctx, idle_seconds=600)
        _wire_queue(ctx, ["k1"])
        ctx.memory_repo.find_by_key.return_value = Success(_memory("k1", importance=0.8))
        worker = EnrichmentWorker(ctx, _config(brain_min_batch_size=1))

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
        ctx = _ctx()
        _idle_ctx(ctx, idle_seconds=600)
        _wire_queue(ctx, ["k1"])
        ctx.memory_repo.find_by_key.return_value = Success(_memory("k1", importance=0.8))
        ctx.vector_store = MagicMock()
        ctx.vector_store.search = AsyncMock(return_value=Success([("old1", 0.9), ("old2", 0.5)]))
        worker = EnrichmentWorker(ctx, _config(brain_min_batch_size=1))

        worker._run_cycle()

        ctx.memory_repo.save_strength.assert_not_called()
        assert [e for e in wiring_events.snapshot_after(0) if e["kind"] == "novelty_gate"] == []

    def test_emits_follow_convention(self) -> None:
        """emit 失敗（raise）でもループは継続する。"""
        ctx = _ctx()
        _idle_ctx(ctx, idle_seconds=600)
        _wire_queue(ctx, ["k1", "k2"])
        ctx.memory_repo.get_strength.side_effect = lambda key: Success(MemoryStrength(memory_key=key))
        ctx.memory_repo.find_by_key.side_effect = lambda key: Success(_memory(key, importance=0.8))
        worker = EnrichmentWorker(ctx, _config(brain_min_batch_size=1))

        with patch.object(wiring_events, "emit", side_effect=RuntimeError("boom")):
            worker._run_cycle()

        assert ctx.memory_repo.save_strength.call_count == 2, "loop must continue after emit failure"


class TestSessionEventRepoLastActivity:
    def test_last_activity_at(self, sqlite_conn) -> None:
        from datetime import datetime

        from nous.domain.memory.session_event import SessionEvent
        from nous.infrastructure.sqlite.session_event_repo import SessionEventRepository

        repo = SessionEventRepository(sqlite_conn)
        ts = datetime(2026, 1, 1, 12, 0, 0)
        repo.insert(
            SessionEvent(
                session_id="s1",
                persona="test",
                event_type="chat.message",
                timestamp=ts,
                summary="hello",
                detail=None,
                metadata=None,
            )
        )
        repo.insert(
            SessionEvent(
                session_id="s1",
                persona="test",
                event_type="chat.message",
                timestamp=ts + timedelta(minutes=5),
                summary="later",
                detail=None,
                metadata=None,
            )
        )
        repo.insert(
            SessionEvent(
                session_id="s1",
                persona="other",
                event_type="chat.message",
                timestamp=ts + timedelta(hours=9),
                summary="other persona",
                detail=None,
                metadata=None,
            )
        )
        assert repo.last_activity_at("test") == ts + timedelta(minutes=5)
        assert repo.last_activity_at("nobody") is None


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
