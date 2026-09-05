"""Task 4: search API truthfulness — limit clamp + invalid-kind filter."""

from __future__ import annotations

import os
import shutil
import tempfile
from unittest.mock import patch

import httpx
import pytest

from nous.application.use_cases import AppContextRegistry
from nous.config.runtime_config import RuntimeConfigManager
from nous.domain.search.engine import SearchEngine, SearchResult
from nous.main import create_app


@pytest.fixture()
def tmp_data_dir():
    d = tempfile.mkdtemp(prefix="search_api_")
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture()
def _reset_singletons():
    AppContextRegistry.close_all()
    AppContextRegistry._settings = None
    RuntimeConfigManager.reset()
    import nous.config.settings as _s

    _s.get_settings.cache_clear()
    yield
    AppContextRegistry.close_all()
    AppContextRegistry._settings = None
    RuntimeConfigManager.reset()
    _s.get_settings.cache_clear()


@pytest.fixture()
def _no_preload(monkeypatch):
    from nous.application import use_cases

    monkeypatch.setattr(use_cases.AppContext, "_preload_background", lambda self: None)


@pytest.fixture()
async def client(tmp_data_dir, _reset_singletons, _no_preload):
    from pathlib import Path

    env_overrides = {
        "NOUS_DATA_ROOT": tmp_data_dir,
        "NOUS_SERVER__HOST": "127.0.0.1",
        "NOUS_SERVER__PORT": "19997",
        "NOUS_QDRANT__URL": "http://localhost:1",
        "NOUS_FORGETTING__ENABLED": "false",
        "NOUS_LOG_LEVEL": "WARNING",
        "NOUS_IMPORT_DIR": "",
    }
    with patch.dict(os.environ, env_overrides, clear=False):
        app_mcp = create_app()
        # auto-create persona dir (memory-DoS guard requires existing dir)
        from nous.application import use_cases as _uc

        if _uc.AppContextRegistry._settings is not None:
            Path(_uc.AppContextRegistry._settings.persona_dir).joinpath("search_api_test").mkdir(
                parents=True, exist_ok=True
            )
        starlette_app = app_mcp.streamable_http_app()
        transport = httpx.ASGITransport(app=starlette_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
            yield ac


def _make_result(kind: str = "episodic") -> SearchResult:
    from datetime import datetime

    from nous.domain.memory.entities import Memory

    now = datetime.now()
    mem = Memory(key="k1", content="test", kind=kind, created_at=now, updated_at=now)
    return SearchResult(memory=mem, score=1.0, source="keyword")


def test_filter_by_kind_invalid_returns_empty():
    assert SearchEngine._filter_by_kind([_make_result()], "not_a_kind") == []


async def test_search_limit_clamped(client):
    r = await client.get("/api/search/search_api_test?q=x&limit=9999")
    assert r.status_code == 200
    assert r.json()["limit"] <= 100
