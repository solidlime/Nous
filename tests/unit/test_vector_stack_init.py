"""Vector stack 初期化の競合回帰テスト.

症状 (2026-09-28): 起動時に warmup thread が vector store 初期化の完了を待たずに
SearchEngine を構築し、semantic=None の engine を永久キャッシュ → semantic 検索が
一切寄与しない（候補充足率 1.1% / zero-result 3/12）。

対象: nous/application/context/vector_stack.py の search_engine プロパティと
_init_vector_store の single-init、EmbeddingModel の load-once / load-failure。
"""

from __future__ import annotations

import asyncio
import logging
import threading
from unittest.mock import MagicMock, patch

import pytest

from nous.application.use_cases import AppContext
from nous.config.settings import Settings


def _make_ctx(tmp_path):
    """AppContext with background preload + Qdrant init disabled (deterministic)."""
    settings = Settings(data_root=str(tmp_path))
    with (
        patch.object(AppContext, "_init_vector_store", lambda self: None),
        patch.object(AppContext, "_preload_background", lambda self: None),
    ):
        return AppContext(settings, "test_persona")


# ---------------------------------------------------------------------------
# search_engine property — vector store 初期化待ち / self-healing
# ---------------------------------------------------------------------------


class TestSearchEngineVectorStoreRace:
    def test_search_engine_uses_lazy_vector_store_property(self, tmp_path):
        """生フィールドではなく lazy-init プロパティを参照する（race の直接原因）。"""

        def _init(self):
            # simulate the background init finishing just before warmup reads it
            self._vector_store = MagicMock()

        settings = Settings(data_root=str(tmp_path))
        with (
            patch.object(AppContext, "_init_vector_store", _init),
            patch.object(AppContext, "_preload_background", lambda self: None),
        ):
            ctx = AppContext(settings, "test_persona")
            assert ctx._vector_store is None
            se = ctx.search_engine

        assert se._semantic is not None
        ctx.close()

    def test_search_engine_self_heals_when_store_becomes_ready(self, tmp_path):
        """初回 build 時に store 未準備でも、準備後に再構築して semantic を復活させる。"""
        ctx = _make_ctx(tmp_path)
        first = ctx.search_engine
        assert first._semantic is None

        ctx._vector_store = MagicMock()  # background init completed later
        second = ctx.search_engine

        assert second is not first
        assert second._semantic is not None
        ctx.close()

    def test_search_engine_not_rebuilt_when_store_permanently_unavailable(self, tmp_path):
        """store が None のまま（Qdrant 不在）なら毎回 rebuild しない。"""
        ctx = _make_ctx(tmp_path)
        first = ctx.search_engine
        second = ctx.search_engine
        assert first is second
        assert first._semantic is None
        ctx.close()

    def test_search_engine_rebuild_invalidates_query_cache(self, tmp_path):
        """rebuild 時に query cache を無効化する（旧 keyword-only 結果の stale 防止）。"""
        from nous.domain.search import engine as engine_mod

        ctx = _make_ctx(tmp_path)
        first = ctx.search_engine
        assert first._semantic is None

        # 旧 engine が keyword-only 結果を cache した状態をシミュレート
        engine_mod._query_cache[("stale",)] = (0.0, [])

        ctx._vector_store = MagicMock()  # background init completed later
        second = ctx.search_engine

        assert second is not first
        assert second._semantic is not None
        assert engine_mod._query_cache == {}
        ctx.close()

    def test_search_engine_built_once_under_concurrent_access(self, tmp_path):
        """並行アクセスでも SearchEngine / semantic は一度だけ構築される。"""
        ctx = _make_ctx(tmp_path)
        ctx._vector_store = MagicMock()

        built: list[int] = []

        def _factory(*args, **kwargs):
            built.append(1)
            return MagicMock()

        engines: list = []

        def _access():
            engines.append(ctx.search_engine)

        with patch("nous.application.use_cases.QdrantSemanticSearch", side_effect=_factory):
            threads = [threading.Thread(target=_access) for _ in range(8)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

        assert len(built) == 1
        assert len({id(e) for e in engines}) == 1
        ctx.close()


# ---------------------------------------------------------------------------
# vector store single-init across threads
# ---------------------------------------------------------------------------


class TestVectorStoreSingleInit:
    def test_init_vector_store_runs_async_init_once(self, tmp_path):
        ctx = _make_ctx(tmp_path)
        calls: list[int] = []

        async def _fake_async():
            calls.append(1)
            await asyncio.sleep(0.05)
            return MagicMock()

        ctx._init_vector_store_async = _fake_async  # type: ignore[method-assign]

        threads = [threading.Thread(target=ctx._init_vector_store) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(calls) == 1
        assert ctx._vector_store is not None
        ctx.close()


# ---------------------------------------------------------------------------
# EmbeddingModel — load-once / load-failure
# ---------------------------------------------------------------------------


class TestEmbeddingModelLoad:
    def test_ensure_loaded_loads_model_once(self):
        from nous.infrastructure.embedding.model import EmbeddingModel

        model = EmbeddingModel()
        loads: list[int] = []

        def _load(self):
            loads.append(1)
            self._session = MagicMock()

        with patch.object(EmbeddingModel, "_load_model", _load):
            threads = [threading.Thread(target=model._ensure_loaded) for _ in range(8)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

        assert len(loads) == 1
        assert model.is_loaded is True

    def test_load_failure_logs_warning_and_stays_unloaded(self, caplog):
        from nous.infrastructure.embedding.model import EmbeddingModel

        model = EmbeddingModel()

        def _load(self):
            raise RuntimeError("onnx download failed")

        with patch.object(EmbeddingModel, "_load_model", _load), caplog.at_level(logging.WARNING):
            model._load_worker()

        assert model.is_loaded is False
        assert model._bg_load_started is False  # self-healing: retry allowed
        assert any("Background model load failed" in r.getMessage() for r in caplog.records)

    @pytest.mark.asyncio
    async def test_vector_store_search_degrades_when_embedding_unloaded(self):
        """未ロード時は semantic をブロックせず空結果 + 背景ロードを kick する（is_loaded ガード）。"""
        from nous.infrastructure.qdrant.adapter import QdrantVectorStore

        emb = MagicMock()
        emb.is_loaded = False
        emb.ensure_loaded_background = MagicMock()
        store = QdrantVectorStore(MagicMock(), emb, "memory_")

        result = await store.search("test_persona", "query", limit=5)

        assert result.is_ok
        assert result.value == []
        emb.ensure_loaded_background.assert_called_once()
