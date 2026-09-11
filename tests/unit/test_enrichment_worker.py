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
from types import SimpleNamespace
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
    cfg.brain_monologue_enabled = False
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


class _FakeMonologueGenerator:
    """MonologueGenerator フェイク (worker フックのテスト用)。"""

    def __init__(self, text: str = "ふふ、いい夢だった。", fail: bool = False) -> None:
        self.text = text
        self.fail = fail
        self.calls: list[tuple[str, list[str]]] = []

    async def generate(self, persona: str, memory_texts: list[str]) -> str | None:
        self.calls.append((persona, memory_texts))
        if self.fail:
            raise RuntimeError("boom")
        return self.text


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


class TestIntrospectionHook:
    """drain 完了後の内省フック (spec §2)。run_introspection は stub し worker 結線のみ検証。"""

    def _worker(self, ctx, keys, engine=None, *, disable=False):
        memories = [_memory(k) for k in keys]
        ctx.memory_repo.find_by_key.side_effect = lambda key: Success(next(m for m in memories if m.key == key))
        _wire_queue(ctx, keys)
        _idle_ctx(ctx, idle_seconds=600)
        cfg = _config(brain_monologue_enabled=False, brain_min_batch_size=1)
        cfg.brain_introspection_enabled = not disable
        if engine is not None:
            ctx.introspection_engine = engine
        return EnrichmentWorker(ctx, cfg)

    def _cycle(self, worker) -> None:
        with (
            patch("nous.application.workers.enrichment_worker.MemoryEnrichService") as svc_cls,
            patch("nous.application.chat.introspection.run_introspection", new_callable=AsyncMock) as run,
        ):
            svc_cls.return_value.enrich_memory = AsyncMock()
            worker._run_cycle()
            return run

    def test_drain_runs_introspection_with_texts(self) -> None:
        ctx = _ctx()
        engine = MagicMock()
        worker = self._worker(ctx, ["k1", "k2"], engine=engine)

        run = self._cycle(worker)

        assert run.await_count == 1
        args = run.await_args.args
        assert args[0] is ctx
        assert args[1] is worker._config
        assert args[2] is engine
        assert args[3] == ["内容 k1", "内容 k2"]

    def test_drained_empty_still_runs_when_new_turns_exist(self) -> None:
        """pending が min_batch 未満（drained 空）でもフックは呼ばれる。"""
        ctx = _ctx()
        ctx.enrichment_queue.pending_keys.return_value = []
        worker = self._worker(ctx, [])

        run = self._cycle(worker)

        assert run.await_count == 1
        assert run.await_args.args[3] == []

    def test_disabled_config_does_not_call_introspection(self) -> None:
        """brain_introspection_enabled=False → 実物 run_introspection がガードし generate 不呼び出し。"""
        ctx = _ctx()
        engine = MagicMock()
        engine.generate = AsyncMock()
        worker = self._worker(ctx, ["k1", "k2", "k3"], engine=engine, disable=True)

        with patch("nous.application.workers.enrichment_worker.MemoryEnrichService") as svc_cls:
            svc_cls.return_value.enrich_memory = AsyncMock()
            worker._run_cycle()

        engine.generate.assert_not_called()

    def test_active_persona_skips_introspection(self) -> None:
        """idle でない → drain もフックも実行しない。"""
        ctx = _ctx()
        memories = [_memory(k) for k in ["k1"]]
        ctx.memory_repo.find_by_key.side_effect = lambda key: Success(next(m for m in memories if m.key == key))
        _wire_queue(ctx, ["k1"])
        _idle_ctx(ctx, idle_seconds=5)
        cfg = _config(brain_min_batch_size=1)
        cfg.brain_introspection_enabled = True
        worker = EnrichmentWorker(ctx, cfg)

        run = self._cycle(worker)

        run.assert_not_called()

    def test_introspection_failure_does_not_break_cycle(self) -> None:
        ctx = _ctx()
        worker = self._worker(ctx, ["k1", "k2", "k3"])

        with (
            patch("nous.application.workers.enrichment_worker.MemoryEnrichService") as svc_cls,
            patch("nous.application.chat.introspection.run_introspection", side_effect=RuntimeError("boom")),
        ):
            svc_cls.return_value.enrich_memory = AsyncMock()
            worker._run_cycle()

        assert ctx.enrichment_queue.mark_processed.call_count == 3


class TestRegistryPersonaConfigLoad:
    """registry.get(persona) config 無し時に persona config.json を読む (バグ修正)."""

    def setup_method(self) -> None:
        AppContextRegistry._contexts.clear()
        AppContextRegistry._enrichment_workers.clear()
        AppContextRegistry._decay_workers.clear()

    def teardown_method(self) -> None:
        AppContextRegistry._contexts.clear()
        AppContextRegistry._enrichment_workers.clear()
        AppContextRegistry._decay_workers.clear()

    def test_config_argument_loaded_from_persona_config_json(self, tmp_path, monkeypatch) -> None:
        persona_dir = tmp_path / "persona" / "p1"
        persona_dir.mkdir(parents=True)
        (persona_dir / "config.json").write_text(
            '{"brain_enrich_auto_run": true, "memory_enrichment_enabled": true}', encoding="utf-8"
        )
        settings = MagicMock()
        settings.persona_dir = str(tmp_path / "persona")
        settings.forgetting.enabled = False
        AppContextRegistry.configure(settings)

        fake_settings = MagicMock()
        fake_settings.data_root = str(tmp_path)
        monkeypatch.setattr("nous.config.settings.get_settings", lambda: fake_settings)

        with (
            patch("nous.application.use_cases.AppContext") as mock_app_ctx,
            patch("nous.application.workers.enrichment_worker.EnrichmentWorker"),
        ):
            AppContextRegistry.get("p1")
            cfg = mock_app_ctx.call_args.kwargs["config"]
            assert cfg is not None
            assert cfg.brain_enrich_auto_run is True
            assert cfg.memory_enrichment_enabled is True

    def test_no_config_json_keeps_none(self, tmp_path, monkeypatch) -> None:
        """config.json 無し → config は None のまま（settings 鎖の契約を維持）."""
        (tmp_path / "persona" / "p1").mkdir(parents=True)
        settings = MagicMock()
        settings.persona_dir = str(tmp_path / "persona")
        settings.forgetting.enabled = False
        AppContextRegistry.configure(settings)

        fake_settings = MagicMock()
        fake_settings.data_root = str(tmp_path)
        monkeypatch.setattr("nous.config.settings.get_settings", lambda: fake_settings)

        with patch("nous.application.use_cases.AppContext") as mock_app_ctx:
            AppContextRegistry.get("p1")
            assert mock_app_ctx.call_args.kwargs["config"] is None


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


class TestRunAsyncDrainsPendingTasks:
    """_run_async は temp loop を close する — コルーチン内 spawn の pending task を
    close 前に drain しないと 'Task was destroyed but it is pending!' になる (2026-09-08 実機)。
    """

    def _worker(self) -> EnrichmentWorker:
        return EnrichmentWorker(MagicMock(), _config())

    def test_background_task_completes_before_loop_close(self) -> None:
        import asyncio
        import threading

        done = threading.Event()
        flag: list[str] = []

        async def coro() -> None:
            async def bg() -> None:
                await asyncio.sleep(0.05)
                done.set()
                flag.append("ok")

            asyncio.create_task(bg())
            await asyncio.sleep(0.01)

        self._worker()._run_async(coro())
        assert done.wait(timeout=2.0), "spawn された task が loop close 前に完遂していない"
        assert flag == ["ok"]

    def test_unfinishable_task_is_cancelled_not_destroyed(self) -> None:
        import asyncio
        import threading

        cancelled = threading.Event()

        async def coro() -> None:
            async def never() -> None:
                try:
                    await asyncio.sleep(100)
                except asyncio.CancelledError:
                    cancelled.set()
                    raise

            asyncio.create_task(never())
            await asyncio.sleep(0.01)

        self._worker()._run_async(coro())
        assert cancelled.wait(timeout=2.0), "残タスクはキャンセルされて loop を閉じるべき"


class TestWorkerStartLog:
    def test_start_logs_info(self, caplog) -> None:
        import logging

        worker = EnrichmentWorker(MagicMock(), _config())
        with (
            caplog.at_level(logging.INFO, logger="nous.application.workers.enrichment_worker"),
            patch("nous.application.workers.enrichment_worker.threading.Thread") as mock_thread,
        ):
            worker.start()
        assert mock_thread.return_value.start.called
        assert any("EnrichmentWorker started" in r.message for r in caplog.records if r.levelname == "INFO")


class TestSpontaneousIntrospection:
    """自発的内省の発火ガード（worker 側）。

    条件: brain_spontaneous_enabled AND engine AND idle 達成 AND
    brain.introspection_spontaneous の最新タイムスタンプから interval_hours 以上経過。
    ターン駆動 brain.introspection はクロックに算入しない (spec B)。
    """

    def _worker(self, ctx: MagicMock, enabled: bool = True, interval_hours: int = 6) -> EnrichmentWorker:
        ctx.introspection_engine = MagicMock()
        ctx._session_event_repo = MagicMock()
        return EnrichmentWorker(
            ctx, _config(brain_spontaneous_enabled=enabled, brain_spontaneous_interval_hours=interval_hours)
        )

    def _repo_with_last(self, ctx: MagicMock, hours_ago: float | None) -> MagicMock:
        repo = ctx._session_event_repo
        if hours_ago is None:
            repo.get_by_persona.return_value = []
        else:
            from nous.domain.shared.time_utils import get_now

            ev = SimpleNamespace(timestamp=get_now() - timedelta(hours=hours_ago))
            repo.get_by_persona.return_value = [ev]
        return repo

    def _patch_run(self):
        return patch("nous.application.chat.introspection.run_spontaneous")

    def test_fires_when_interval_elapsed(self) -> None:

        ctx = MagicMock()
        worker = self._worker(ctx)
        self._repo_with_last(ctx, hours_ago=7.0)
        with self._patch_run() as mock_run:
            worker._maybe_spontaneous(25200.0)
        assert mock_run.called
        args = mock_run.call_args
        assert args.args[0] is ctx
        assert args.kwargs["idle_seconds"] == 25200.0

    def test_turn_introspection_does_not_block_spontaneous(self) -> None:
        """ターン駆動が最近でも、自発クロックは spontaneous のみ参照 → 発火する。"""
        ctx = MagicMock()
        worker = self._worker(ctx)
        repo = ctx._session_event_repo

        def by_persona(persona, etype, limit):
            from nous.domain.shared.time_utils import get_now

            if etype == "brain.introspection":
                return [SimpleNamespace(timestamp=get_now() - timedelta(minutes=10))]
            return [SimpleNamespace(timestamp=get_now() - timedelta(hours=10))]

        repo.get_by_persona.side_effect = by_persona
        with self._patch_run() as mock_run:
            worker._maybe_spontaneous(600.0)
        assert mock_run.called

    def test_no_history_fires(self) -> None:
        ctx = MagicMock()
        worker = self._worker(ctx)
        self._repo_with_last(ctx, hours_ago=None)
        with self._patch_run() as mock_run:
            worker._maybe_spontaneous(3600.0)
        assert mock_run.called

    def test_disabled_no_fire(self) -> None:
        ctx = MagicMock()
        worker = self._worker(ctx, enabled=False)
        with self._patch_run() as mock_run:
            worker._maybe_spontaneous(3600.0)
        assert not mock_run.called

    def test_no_engine_no_fire(self) -> None:
        ctx = MagicMock()
        ctx.introspection_engine = None
        worker = self._worker(ctx)
        ctx.introspection_engine = None
        with self._patch_run() as mock_run:
            worker._maybe_spontaneous(3600.0)
        assert not mock_run.called

    def test_run_cycle_reaches_spontaneous_when_idle(self) -> None:
        """_run_cycle が idle 達成時に _maybe_spontaneous を呼ぶこと。"""
        ctx = MagicMock()
        worker = self._worker(ctx)
        self._repo_with_last(ctx, hours_ago=None)
        ctx.enrichment_queue.pending_keys.return_value = []
        ctx._session_event_repo.last_activity_at.return_value = None  # idle None → not idle
        # idle None は「not idle」扱い → 自発も発火しない（既存 idle gate 流用）
        with patch.object(worker, "_maybe_spontaneous") as mock_sp:
            worker._run_cycle()
        assert not mock_sp.called

        # idle 達成
        from datetime import timedelta as td

        from nous.domain.shared.time_utils import get_now

        ctx._session_event_repo.last_activity_at.return_value = get_now() - td(hours=1)
        with patch.object(worker, "_maybe_spontaneous") as mock_sp:
            worker._run_cycle()
        assert mock_sp.called
