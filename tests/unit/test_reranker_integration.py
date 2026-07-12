"""Tests for RerankerModel integration into AppContext and SearchEngine.

TDD: Write failing tests first, then implement.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from nous.domain.memory.entities import Memory
from nous.domain.search.engine import SearchEngine, SearchQuery, SearchResult
from nous.domain.shared.result import Success

# ---------------------------------------------------------------------------
# RerankerModel unit tests
# ---------------------------------------------------------------------------


class TestRerankerModelScoreBlending:
    """Verify RerankerModel.rerank blends cross-encoder scores with original scores.

    This catches a bug where zip() was called with ``pairs`` instead of
    ``scores``.
    """

    def test_blends_scores_correctly(self):
        """Cross-encoder scores (70 %) + original score (30 %) → combined ranking."""
        from nous.infrastructure.embedding.reranker import RerankerModel

        model = RerankerModel(model_name="test-model", enabled=True)
        model._session = MagicMock()
        model._tokenizer = MagicMock()
        # Two documents: doc1 gets high CE score, doc2 gets low CE score
        # ONNX の reranker は sigmoid(logit) → score なので logit を渡す
        model._session.run.return_value = [
            np.array(
                [[2.1972245773362196], [-0.8472978603872037]],  # logit(0.9), logit(0.3)
                dtype=np.float32,
            )
        ]
        # tokenizer.encode → ダミーの encoding (ids + attention_mask)
        model._tokenizer.encode.return_value = MagicMock(
            ids=[101, 102, 103, 104, 105],
            attention_mask=[1, 1, 1, 1, 1],
        )

        results = [("key1", 0.5), ("key2", 0.8)]
        contents = {"key1": "document one content", "key2": "document two content"}

        reranked = model.rerank("test query", results, contents, top_k=2)

        # Expected blended scores:
        # key1: 0.9 * 0.7 + 0.5 * 0.3 = 0.63 + 0.15 = 0.78
        # key2: 0.3 * 0.7 + 0.8 * 0.3 = 0.21 + 0.24 = 0.45
        # Sorted: key1 (0.78) → key2 (0.45)
        assert len(reranked) == 2
        assert reranked[0][0] == "key1", "key1 should rank first after rerank"
        assert reranked[1][0] == "key2"
        assert abs(reranked[0][1] - 0.78) < 1e-6, f"Expected 0.78, got {reranked[0][1]}"
        assert abs(reranked[1][1] - 0.45) < 1e-6, f"Expected 0.45, got {reranked[1][1]}"

    def test_disabled_returns_original_order(self):
        """When enabled=False, rerank() returns original results sliced to top_k."""
        from nous.infrastructure.embedding.reranker import RerankerModel

        model = RerankerModel(model_name="test-model", enabled=False)
        results = [("key1", 0.9), ("key2", 0.5)]
        contents = {"key1": "doc1", "key2": "doc2"}
        reranked = model.rerank("query", results, contents, top_k=1)
        assert len(reranked) == 1
        assert reranked[0][0] == "key1"

    def test_empty_results_returns_empty(self):
        """Empty results list returns empty list."""
        from nous.infrastructure.embedding.reranker import RerankerModel

        model = RerankerModel(model_name="test-model", enabled=True)
        model._session = MagicMock()
        reranked = model.rerank("query", [], {}, top_k=5)
        assert reranked == []

    def test_missing_content_skips_rerank(self):
        """When no content is available, original results are returned."""
        from nous.infrastructure.embedding.reranker import RerankerModel

        model = RerankerModel(model_name="test-model", enabled=True)
        model._session = MagicMock()
        model._tokenizer = MagicMock()
        results = [("key1", 0.9)]
        reranked = model.rerank("query", results, {}, top_k=5)
        assert len(reranked) == 1
        assert reranked[0][0] == "key1"


# ---------------------------------------------------------------------------
# SearchEngine reranker integration tests
# ---------------------------------------------------------------------------


def _make_mem(key: str, content: str = "content") -> Memory:
    from datetime import UTC, datetime

    return Memory(
        key=key,
        content=content,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def _make_result(key: str, score: float, source: str = "keyword", content: str = "content") -> SearchResult:
    return SearchResult(memory=_make_mem(key, content), score=score, source=source)


class TestSearchEngineRerankerIntegration:
    """SearchEngine._hybrid_search should apply reranker when configured."""

    @pytest.mark.asyncio
    async def test_reranker_called_when_enabled(self):
        """When a reranker is set and enabled, _hybrid_search should call rerank."""

        # Mock the reranker
        mock_reranker = MagicMock()
        mock_reranker.enabled = True
        mock_reranker.rerank.return_value = [("key_b", 0.9), ("key_a", 0.5)]

        # Create SearchEngine with mocked strategies
        kw = MagicMock()
        kw.search.return_value = Success([(_make_mem("key_a"), 0.5), (_make_mem("key_b"), 0.8)])

        engine = SearchEngine(keyword_search=kw, reranker=mock_reranker)
        result = await engine.search(SearchQuery(text="test", mode="hybrid", top_k=5))
        assert result.is_ok

        # reranker.rerank should have been called
        mock_reranker.rerank.assert_called_once()

    @pytest.mark.asyncio
    async def test_reranker_scores_merged_into_results(self):
        """Reranked scores should replace SearchResult scores after rerank."""

        mock_reranker = MagicMock()
        mock_reranker.enabled = True
        # Reranker gives key_b higher score than key_a
        mock_reranker.rerank.return_value = [("key_b", 0.95), ("key_a", 0.45)]

        kw = MagicMock()
        mem_a = _make_mem("key_a", content="aaa")
        mem_b = _make_mem("key_b", content="bbb")
        kw.search.return_value = Success([(mem_a, 0.5), (mem_b, 0.8)])

        engine = SearchEngine(keyword_search=kw, reranker=mock_reranker)
        result = await engine.search(SearchQuery(text="test", mode="hybrid", top_k=5))
        assert result.is_ok
        assert len(result.value) >= 2
        # key_b should now be first with higher score
        assert result.value[0].memory.key == "key_b"
        assert result.value[0].score == 0.95

    @pytest.mark.asyncio
    async def test_reranker_not_called_when_none(self):
        """When reranker is None, _hybrid_search should skip rerank."""

        kw = MagicMock()
        kw.search.return_value = Success([(_make_mem("key_a"), 0.5)])

        engine = SearchEngine(keyword_search=kw, reranker=None)
        result = await engine.search(SearchQuery(text="test", mode="hybrid", top_k=5))
        assert result.is_ok
        # Just verifies no crash

    @pytest.mark.asyncio
    async def test_reranker_not_called_when_disabled(self):
        """When reranker.enabled is False, _hybrid_search should skip rerank."""

        mock_reranker = MagicMock()
        mock_reranker.enabled = False

        kw = MagicMock()
        kw.search.return_value = Success([(_make_mem("key_a"), 0.5)])

        engine = SearchEngine(keyword_search=kw, reranker=mock_reranker)
        result = await engine.search(SearchQuery(text="test", mode="hybrid", top_k=5))
        assert result.is_ok
        mock_reranker.rerank.assert_not_called()


# ---------------------------------------------------------------------------
# AppContext RerankerModel instantiation tests
# ---------------------------------------------------------------------------


class TestAppContextRerankerInstantiation:
    """AppContext should instantiate RerankerModel with correct configuration."""

    def test_reranker_instantiated_with_config(self, tmp_path):
        """RerankerModel should be created with model_name and enabled from settings."""
        from nous.application.use_cases import AppContext
        from nous.config.settings import Settings

        settings = Settings(
            data_root=str(tmp_path),
            reranker={"model": "test-model", "enabled": True},
        )

        with (
            patch("nous.infrastructure.embedding.reranker.RerankerModel") as mock_reranker_cls,
            patch.object(AppContext, "_init_vector_store", return_value=None),
        ):
            ctx = AppContext(settings, "test_persona")

            # RerankerModel should have been instantiated
            mock_reranker_cls.assert_called_once_with(
                model_name="test-model",
                enabled=True,
            )
            ctx.close()

    def test_reranker_not_instantiated_when_disabled(self, tmp_path):
        """Even when disabled, RerankerModel should still be instantiated (config-driven)."""
        from nous.application.use_cases import AppContext
        from nous.config.settings import Settings

        settings = Settings(
            data_root=str(tmp_path),
            reranker={"model": "test-model", "enabled": False},
        )

        with (
            patch("nous.infrastructure.embedding.reranker.RerankerModel") as mock_reranker_cls,
            patch.object(AppContext, "_init_vector_store", return_value=None),
        ):
            ctx = AppContext(settings, "test_persona")

            mock_reranker_cls.assert_called_once_with(
                model_name="test-model",
                enabled=False,
            )
            ctx.close()

    def test_reranker_preload_thread_started_when_enabled(self, tmp_path):
        """When enabled, a background thread should preload the model."""
        from nous.application.use_cases import AppContext
        from nous.config.settings import Settings

        settings = Settings(
            data_root=str(tmp_path),
            reranker={"model": "test-model", "enabled": True},
        )

        with (
            patch("nous.infrastructure.embedding.reranker.RerankerModel") as mock_reranker_cls,
            patch.object(AppContext, "_init_vector_store", return_value=None),
            patch("threading.Thread") as mock_thread,
        ):
            mock_instance = MagicMock()
            mock_reranker_cls.return_value = mock_instance
            mock_instance.enabled = True

            ctx = AppContext(settings, "test_persona")

            # A daemon thread should be started to preload the model;
            # the target is a local wrapper that will call _load_model
            assert mock_thread.return_value.start.called
            ctx.close()

    def test_reranker_not_preloaded_when_disabled(self, tmp_path):
        """When disabled, no preload thread should be started — but vector store init thread is always created."""
        from nous.application.use_cases import AppContext
        from nous.config.settings import Settings

        settings = Settings(
            data_root=str(tmp_path),
            reranker={"model": "test-model", "enabled": False},
        )

        with (
            patch("nous.infrastructure.embedding.reranker.RerankerModel") as mock_reranker_cls,
            patch.object(AppContext, "_init_vector_store", return_value=None),
            patch("threading.Thread") as mock_thread,
        ):
            mock_instance = MagicMock()
            mock_reranker_cls.return_value = mock_instance
            mock_instance.enabled = False  # disabled

            ctx = AppContext(settings, "test_persona")

            # One background thread is always created for _init_vector_store.
            # Reranker preload thread must NOT be created when disabled.
            assert mock_thread.call_count == 1, (
                f"Expected 1 Thread() call (vector store init), got {mock_thread.call_count}"
            )
            ctx.close()
