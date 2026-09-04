"""Regression tests for hot-reload wiring fixes (#081 findings #3/#6/#7).

Covers:
1. qdrant callback runs in a dedicated thread (works even when called from
   inside a running event loop — no asyncio.run RuntimeError).
2. _reload_worker always sets a terminal status even if the iteration raises.
3. register_model_reload_callbacks is idempotent (no duplicate registration).
"""

from __future__ import annotations

import asyncio
import threading
from typing import Any
from unittest.mock import MagicMock

import pytest

from nous.config.runtime_config import (
    RuntimeConfigManager,
    register_model_reload_callbacks,
)


@pytest.fixture
def config_manager() -> RuntimeConfigManager:
    RuntimeConfigManager.reset()
    mgr = RuntimeConfigManager()
    mgr._settings = MagicMock()
    mgr._default_settings = MagicMock()
    return mgr


@pytest.fixture(autouse=True)
def _reset_singleton(config_manager):
    yield
    RuntimeConfigManager.reset()


# ---------------------------------------------------------------------------
# 1. qdrant callback: dedicated thread + own event loop
# ---------------------------------------------------------------------------


class TestQdrantCallbackOffLoop:
    def test_callback_works_inside_running_loop(self, config_manager, monkeypatch):
        """イベントループ内から呼んでも RuntimeError にならず status が terminal まで進む。"""
        registered: dict[str, Any] = {}
        monkeypatch.setattr(
            config_manager,
            "register_callback",
            lambda category, cb: registered.__setitem__(category, cb),
        )
        register_model_reload_callbacks(config_manager)
        cb = registered["qdrant"]
        assert cb is not None

        done = threading.Event()
        statuses: list[str] = []

        original_set = config_manager.reload_status.set

        def tracking_set(key, status, **kwargs):
            original_set(key, status, **kwargs)
            if key == "qdrant" and status in ("ready", "error"):
                statuses.append(status)
                done.set()

        monkeypatch.setattr(config_manager.reload_status, "set", tracking_set)

        # Simulate AppContextRegistry with no contexts (empty iteration → ready)
        import nous.application.use_cases as uc

        monkeypatch.setattr(uc.AppContextRegistry, "_contexts", {})

        async def caller():
            # Called from inside a running loop — old code raised RuntimeError
            cb("url", "http://localhost:6333")

        asyncio.run(caller())
        assert done.wait(timeout=10), "qdrant callback must reach a terminal status"
        assert statuses and statuses[0] in ("ready", "error")


# ---------------------------------------------------------------------------
# 2. _reload_worker: terminal status guaranteed on exception
# ---------------------------------------------------------------------------


def _wait_terminal(config_manager: RuntimeConfigManager, key: str, timeout: float = 10.0) -> str:
    """Wait for a threaded reload to reach a terminal status.

    Phase 1: wait until the worker touches the status (leaves the default 'ready').
    Phase 2: wait until it reaches 'ready' or 'error'.
    """
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if config_manager.reload_status.get(key)["status"] != "ready":
            break
        time.sleep(0.01)
    while time.monotonic() < deadline:
        status = config_manager.reload_status.get(key)["status"]
        if status in ("ready", "error"):
            return status
        time.sleep(0.01)
    return config_manager.reload_status.get(key)["status"]


class TestReloadWorkerTerminalStatus:
    def test_embedding_reload_sets_error_status_on_exception(self, config_manager, monkeypatch):
        """反復中に例外が出ても reload_status が terminal ("error") になる。"""
        registered: dict[str, Any] = {}
        monkeypatch.setattr(
            config_manager,
            "register_callback",
            lambda category, cb: registered.__setitem__(category, cb),
        )
        register_model_reload_callbacks(config_manager)
        cb = registered["embedding"]

        import nous.application.use_cases as uc

        class BoomDict(dict):
            def items(self):
                raise RuntimeError("persona created during iteration")

        monkeypatch.setattr(uc.AppContextRegistry, "_contexts", BoomDict())

        cb("model", "new-model")
        assert _wait_terminal(config_manager, "embedding") == "error"

    def test_reranker_reload_sets_error_status_on_exception(self, config_manager, monkeypatch):
        """reranker 反復中の例外でも terminal status を保証する。"""
        registered: dict[str, Any] = {}
        monkeypatch.setattr(
            config_manager,
            "register_callback",
            lambda category, cb: registered.__setitem__(category, cb),
        )
        register_model_reload_callbacks(config_manager)
        cb = registered["reranker"]

        import nous.application.use_cases as uc

        class BoomDict(dict):
            def items(self):
                raise RuntimeError("persona created during iteration")

        monkeypatch.setattr(uc.AppContextRegistry, "_contexts", BoomDict())

        cb("model", "new-model")
        assert _wait_terminal(config_manager, "reranker") == "error"

    def test_qdrant_reload_sets_error_status_on_exception(self, config_manager, monkeypatch):
        """qdrant 反復中の例外（並行ペルソナ生成 RuntimeError 等）でも terminal status を保証する。"""
        registered: dict[str, Any] = {}
        monkeypatch.setattr(
            config_manager,
            "register_callback",
            lambda category, cb: registered.__setitem__(category, cb),
        )
        register_model_reload_callbacks(config_manager)
        cb = registered["qdrant"]

        import nous.application.use_cases as uc

        class BoomDict(dict):
            def items(self):
                raise RuntimeError("persona created during iteration")

        monkeypatch.setattr(uc.AppContextRegistry, "_contexts", BoomDict())

        cb("url", "http://localhost:6333")
        assert _wait_terminal(config_manager, "qdrant") == "error"


# ---------------------------------------------------------------------------
# 3. register_model_reload_callbacks: idempotent
# ---------------------------------------------------------------------------


class TestIdempotentRegistration:
    def test_double_registration_registers_once(self, config_manager, monkeypatch):
        """2回呼んでもコールバックは1回だけ登録される。"""
        calls: list[str] = []
        monkeypatch.setattr(
            config_manager,
            "register_callback",
            lambda category, cb: calls.append(category),
        )
        register_model_reload_callbacks(config_manager)
        register_model_reload_callbacks(config_manager)
        assert calls.count("embedding") == 1
        assert calls.count("reranker") == 1
        assert calls.count("qdrant") == 1

    def test_reset_allows_re_registration(self, config_manager, monkeypatch):
        """reset() 後は再登録できる（テスト用）。"""
        calls: list[str] = []
        monkeypatch.setattr(
            config_manager,
            "register_callback",
            lambda category, cb: calls.append(category),
        )
        register_model_reload_callbacks(config_manager)
        RuntimeConfigManager.reset()
        register_model_reload_callbacks(config_manager)
        assert calls.count("embedding") == 2
