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


async def test_search_decision_params(client, monkeypatch):
    """decision / hops / request_id query params → SearchQuery に流れる (#011)."""
    from nous.domain.search.engine import SearchEngine
    from nous.domain.shared.result import Success

    captured: dict = {}

    async def _fake_search(self, query):
        captured["query"] = query
        return Success([])

    monkeypatch.setattr(SearchEngine, "search", _fake_search)
    r = await client.get("/api/search/search_api_test?q=x&decision=1&hops=3&request_id=abc")
    assert r.status_code == 200
    q = captured["query"]
    assert q.decision_enabled is True
    assert q.max_hops == 3
    assert q.request_id == "abc"
    assert q.decision_threshold == 0.55


async def test_search_decision_default_off(client, monkeypatch):
    from nous.domain.search.engine import SearchEngine
    from nous.domain.shared.result import Success

    captured: dict = {}

    async def _fake_search(self, query):
        captured["query"] = query
        return Success([])

    monkeypatch.setattr(SearchEngine, "search", _fake_search)
    r = await client.get("/api/search/search_api_test?q=x")
    assert r.status_code == 200
    q = captured["query"]
    assert q.decision_enabled is False
    assert q.max_hops == 1
    assert q.request_id is None


async def test_search_project_param_boosts_tagged_memory(client, monkeypatch):
    """``project`` 指定で ``project:<slug>`` タグ保持の記憶が持ち上がり、応答に project が返る。"""
    from datetime import datetime

    from nous.domain.memory.entities import Memory
    from nous.domain.search.engine import SearchEngine, SearchResult
    from nous.domain.shared.result import Success

    now = datetime.now()

    def _hit(key: str, tags: list[str], score: float) -> SearchResult:
        mem = Memory(key=key, content=key, kind="semantic", created_at=now, updated_at=now, tags=tags)
        return SearchResult(memory=mem, score=score, source="keyword")

    async def _fake_search(self, query):
        return Success([_hit("other", ["misc"], 1.0), _hit("proj", ["project:nous"], 0.9)])

    monkeypatch.setattr(SearchEngine, "search", _fake_search)

    plain = (await client.get("/api/search/search_api_test?q=x")).json()
    assert plain["project"] is None
    assert [row["memory"]["key"] for row in plain["results"]] == ["other", "proj"]

    r = await client.get("/api/search/search_api_test?q=x&project=NOUS")
    body = r.json()
    assert body["project"] == "nous"
    assert [row["memory"]["key"] for row in body["results"]] == ["proj", "other"]
    assert body["results"][0]["score"] == pytest.approx(1.125)


async def test_search_project_param_invalid_is_ignored(client, monkeypatch):
    """canonical slug 規約に合わない project は None として扱う（400 にしない）。"""
    from nous.domain.search.engine import SearchEngine
    from nous.domain.shared.result import Success

    async def _fake_search(self, query):
        return Success([])

    monkeypatch.setattr(SearchEngine, "search", _fake_search)
    r = await client.get("/api/search/search_api_test?q=x&project=%%%")
    assert r.status_code == 200
    assert r.json()["project"] is None


def test_apply_project_boost_is_pure_for_rows_without_project_tag():
    """タグ無し行は素通り（順序も値も変えない）。"""
    from nous.api.http.routers.search import apply_project_boost

    rows = [{"memory": {"key": "a", "tags": ["misc"]}, "score": 1.0, "source": "keyword"}]
    assert apply_project_boost(rows, "") == rows
    assert apply_project_boost(rows, "nous") == rows


async def test_search_project_widens_candidate_pool(client, monkeypatch):
    """``project`` 指定時は top_k を広げてからブーストする（4 位以下の記憶も昇格できる）。"""
    from datetime import datetime

    from nous.domain.memory.entities import Memory
    from nous.domain.search.engine import SearchEngine, SearchResult
    from nous.domain.shared.result import Success

    now = datetime.now()
    captured: dict = {}

    def _hit(key: str, tags: list[str], score: float) -> SearchResult:
        mem = Memory(key=key, content=key, kind="semantic", created_at=now, updated_at=now, tags=tags)
        return SearchResult(memory=mem, score=score, source="keyword")

    # engine 側は top_k で切るので、テストでも top_k を尊重して返す
    rows = [
        _hit("a", ["misc"], 1.0),
        _hit("b", ["misc"], 0.95),
        _hit("c", ["misc"], 0.9),
        _hit("proj", ["project:nous"], 0.85),
    ]

    async def _fake_search(self, query):
        captured["top_k"] = query.top_k
        return Success(rows[: query.top_k])

    monkeypatch.setattr(SearchEngine, "search", _fake_search)

    plain = (await client.get("/api/search/search_api_test?q=x&limit=2")).json()
    assert captured["top_k"] == 2
    assert [row["memory"]["key"] for row in plain["results"]] == ["a", "b"]

    boosted = (await client.get("/api/search/search_api_test?q=x&limit=2&project=nous")).json()
    assert captured["top_k"] == 6  # プール拡張（本命は下の順序 assert。ここは仕様の目印）
    assert len(boosted["results"]) == 2
    assert [row["memory"]["key"] for row in boosted["results"]] == ["proj", "a"]


async def test_project_boost_sorts_by_final_rank_key(client, monkeypatch):
    """並べ替えは engine と同じ ``score * time_weight``。score だけのソートなら落ちる。"""
    from datetime import timedelta

    from nous.domain.memory.entities import Memory
    from nous.domain.search.engine import SearchEngine, SearchResult
    from nous.domain.shared.result import Success
    from nous.domain.shared.time_utils import get_now

    today = get_now()
    old = today - timedelta(days=30)

    def _hit(key: str, tags: list[str], score: float, *, created_at, time_weight: float) -> SearchResult:
        mem = Memory(key=key, content=key, kind="semantic", created_at=created_at, updated_at=created_at, tags=tags)
        return SearchResult(memory=mem, score=score, source="keyword", time_weight=time_weight)

    rows = [
        # project 記憶。ブースト後スコアは 1.125 だが、時間減衰で実効 0.5625
        _hit("proj-old", ["project:nous"], 0.9, created_at=old, time_weight=0.5),
        # project なし。スコア 1.0 のまま、実効 1.0
        _hit("plain-fresh", ["misc"], 1.0, created_at=today, time_weight=1.0),
    ]

    async def _fake_search(self, query):
        return Success(rows[: query.top_k])

    monkeypatch.setattr(SearchEngine, "search", _fake_search)

    body = (await client.get("/api/search/search_api_test?q=x&limit=2&project=nous")).json()
    # score だけなら proj-old(1.125) が先。実効キーなら plain-fresh(1.0) が先。
    assert [row["memory"]["key"] for row in body["results"]] == ["plain-fresh", "proj-old"]
    assert body["results"][1]["score"] == 1.125  # 表示スコアはブースト後のまま
    assert body["results"][1]["time_weight"] == 0.5
