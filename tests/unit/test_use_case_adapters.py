"""Tests for application use case adapters."""

from __future__ import annotations

from datetime import UTC, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nous.application.use_cases import QdrantSemanticSearch, SQLiteKeywordSearch
from nous.domain.memory.entities import Memory
from nous.domain.shared.result import Failure, Success
from nous.domain.shared.time_utils import get_now


def _make_memory(key="mem_001", content="test", created_at=None):
    now = created_at or get_now()
    return Memory(key=key, content=content, created_at=now, updated_at=now)


class TestSQLiteKeywordSearch:
    def test_init(self):
        repo = MagicMock()
        adapter = SQLiteKeywordSearch(repo)
        assert adapter.repo is repo

    def test_search_success(self):
        memory = _make_memory()
        repo = MagicMock()
        repo.search_keyword.return_value = Success([(memory, 1.0)])

        adapter = SQLiteKeywordSearch(repo)
        result = adapter.search("test")
        assert result.is_ok
        assert len(result.value) == 1

    def test_search_failure(self):
        repo = MagicMock()
        repo.search_keyword.return_value = Failure(Exception("db error"))

        adapter = SQLiteKeywordSearch(repo)
        result = adapter.search("test")
        assert not result.is_ok

    def test_search_passes_limit(self):
        repo = MagicMock()
        repo.search_keyword.return_value = Success([])

        adapter = SQLiteKeywordSearch(repo)
        adapter.search("query", limit=5)
        repo.search_keyword.assert_called_once_with("query", 5, date_from=None, date_to=None, tags=None)


class TestQdrantSemanticSearch:
    def test_init(self):
        vs = MagicMock()
        repo = MagicMock()
        adapter = QdrantSemanticSearch(vs, repo)
        assert adapter.vector_store is vs
        assert adapter.memory_repo is repo
        assert adapter.persona == ""

    @pytest.mark.asyncio
    async def test_search_failure_propagates(self):
        vs = AsyncMock()
        vs.search.return_value = Failure(Exception("qdrant error"))
        repo = MagicMock()

        adapter = QdrantSemanticSearch(vs, repo)
        result = await adapter.search("query")
        assert not result.is_ok

    @pytest.mark.asyncio
    async def test_search_success_with_memory(self):
        memory = _make_memory("mem_001")
        vs = AsyncMock()
        vs.search.return_value = Success([("mem_001", 0.9)])

        repo = MagicMock()
        repo.find_by_key.return_value = Success(memory)

        adapter = QdrantSemanticSearch(vs, repo)
        adapter.persona = "test"
        result = await adapter.search("query")
        assert result.is_ok
        assert len(result.value) == 1
        assert result.value[0][0] is memory
        assert result.value[0][1] == pytest.approx(0.9)

    @pytest.mark.asyncio
    async def test_search_skips_missing_memory(self):
        vs = AsyncMock()
        vs.search.return_value = Success([("mem_missing", 0.9)])

        repo = MagicMock()
        repo.find_by_key.return_value = Success(None)  # not found

        adapter = QdrantSemanticSearch(vs, repo)
        result = await adapter.search("query")
        assert result.is_ok
        assert result.value == []

    @pytest.mark.asyncio
    async def test_search_uses_persona(self):
        vs = AsyncMock()
        vs.search.return_value = Success([])
        repo = MagicMock()

        adapter = QdrantSemanticSearch(vs, repo)
        adapter.persona = "my_persona"
        await adapter.search("query")
        vs.search.assert_called_once_with("my_persona", "query", 10)


class TestQdrantSemanticSearchDateFiltering:
    """Tests for date-based post-filtering in QdrantSemanticSearch.search()."""

    @pytest.fixture
    def vs(self):
        return AsyncMock()

    def _make_naive_memory(self, key: str, content: str, days_ago: int):
        """Create a memory with a timezone-naive created_at (simulating SQLite return)."""
        from datetime import datetime

        naive_dt = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=days_ago)
        return Memory(key=key, content=content, created_at=naive_dt, updated_at=naive_dt)

    @pytest.mark.asyncio
    async def test_date_from_filters_older_memories(self):
        """date_from should exclude memories created before that date."""
        old_mem = self._make_naive_memory("mem_old", "old", days_ago=10)
        new_mem = self._make_naive_memory("mem_new", "new", days_ago=1)

        vs = AsyncMock()
        vs.search.return_value = Success([("mem_old", 0.8), ("mem_new", 0.9)])

        repo = MagicMock()

        def find_by_key(key: str):
            return Success(old_mem if key == "mem_old" else new_mem)

        repo.find_by_key.side_effect = find_by_key

        adapter = QdrantSemanticSearch(vs, repo)
        adapter.persona = "test"
        # date_from = 5 days ago (timezone-aware, as parse_date_range returns)
        from datetime import datetime

        date_from = datetime.now(UTC) - timedelta(days=5)
        result = await adapter.search("query", date_from=date_from)
        assert result.is_ok
        assert len(result.value) == 1
        assert result.value[0][0].key == "mem_new"

    @pytest.mark.asyncio
    async def test_date_to_filters_newer_memories(self):
        """date_to should exclude memories created after that date."""
        old_mem = self._make_naive_memory("mem_old", "old", days_ago=10)
        new_mem = self._make_naive_memory("mem_new", "new", days_ago=1)

        vs = AsyncMock()
        vs.search.return_value = Success([("mem_old", 0.8), ("mem_new", 0.9)])

        repo = MagicMock()

        def find_by_key(key: str):
            return Success(old_mem if key == "mem_old" else new_mem)

        repo.find_by_key.side_effect = find_by_key

        adapter = QdrantSemanticSearch(vs, repo)
        adapter.persona = "test"
        from datetime import datetime

        date_to = datetime.now(UTC) - timedelta(days=5)
        result = await adapter.search("query", date_to=date_to)
        assert result.is_ok
        assert len(result.value) == 1
        assert result.value[0][0].key == "mem_old"

    @pytest.mark.asyncio
    async def test_date_from_and_to_together(self):
        """Both date_from and date_to should filter in the correct range."""
        old = self._make_naive_memory("mem_old", "old", days_ago=20)
        mid = self._make_naive_memory("mem_mid", "mid", days_ago=10)
        new = self._make_naive_memory("mem_new", "new", days_ago=1)

        vs = AsyncMock()
        vs.search.return_value = Success([("mem_old", 0.7), ("mem_mid", 0.8), ("mem_new", 0.9)])

        repo = MagicMock()

        def find_by_key(key: str):
            mapping = {"mem_old": old, "mem_mid": mid, "mem_new": new}
            return Success(mapping[key])

        repo.find_by_key.side_effect = find_by_key

        adapter = QdrantSemanticSearch(vs, repo)
        adapter.persona = "test"
        from datetime import datetime

        date_from = datetime.now(UTC) - timedelta(days=15)
        date_to = datetime.now(UTC) - timedelta(days=5)
        result = await adapter.search("query", date_from=date_from, date_to=date_to)
        assert result.is_ok
        assert len(result.value) == 1
        assert result.value[0][0].key == "mem_mid"

    @pytest.mark.asyncio
    async def test_date_filter_increases_fetch_limit(self):
        """When date filter is active, fetch_limit should be 3x the requested limit."""
        vs = AsyncMock()
        vs.search.return_value = Success([])
        repo = MagicMock()

        adapter = QdrantSemanticSearch(vs, repo)
        adapter.persona = "test"
        from datetime import datetime

        await adapter.search("query", limit=5, date_from=datetime.now(UTC))
        # fetch_limit = 5 * 3 = 15
        vs.search.assert_called_once_with("test", "query", 15)

    @pytest.mark.asyncio
    async def test_date_filter_no_dates_uses_normal_limit(self):
        """Without date filter, fetch_limit should equal the requested limit."""
        vs = AsyncMock()
        vs.search.return_value = Success([])
        repo = MagicMock()

        adapter = QdrantSemanticSearch(vs, repo)
        adapter.persona = "test"
        await adapter.search("query", limit=5)
        vs.search.assert_called_once_with("test", "query", 5)

    @pytest.mark.asyncio
    async def test_break_when_limit_reached_after_date_filter(self):
        """Should break early when enough results pass the date filter (line 75)."""
        from datetime import datetime

        # 4 memories all within date range
        memories = [self._make_naive_memory(f"mem_{i}", f"content {i}", days_ago=i) for i in range(4)]
        vs = AsyncMock()
        vs.search.return_value = Success([(f"mem_{i}", 0.9 - i * 0.1) for i in range(4)])

        repo = MagicMock()

        def find_by_key(key: str):
            idx = int(key.split("_")[1])
            return Success(memories[idx])

        repo.find_by_key.side_effect = find_by_key

        adapter = QdrantSemanticSearch(vs, repo)
        adapter.persona = "test"
        date_from = datetime.now(UTC) - timedelta(days=30)
        result = await adapter.search("query", limit=2, date_from=date_from)
        assert result.is_ok
        assert len(result.value) == 2  # Should break at limit=2


# ──────────────────────────────────────────────
# AppContext / AppContextRegistry tests
# ──────────────────────────────────────────────


class TestAppContextMigration:
    """Tests for AppContext initialization edge cases."""

    def test_memory_enricher_created_with_api_key(self, tmp_path):
        """When memory_enrichment is enabled and api_key is set, MemoryEnricher is created (lines 120-124)."""
        from nous.application.use_cases import AppContext
        from nous.config.settings import Settings

        settings = Settings(
            data_root=str(tmp_path),
            memory_enrichment={
                "enabled": True,
                "api_key": "test-key-123",
                "provider": "openai",
                "model": "gpt-4o",
                "base_url": "https://api.openai.com",
                "min_chars": 100,
            },
        )

        with patch("nous.infrastructure.llm.memory_enricher.MemoryEnricher") as mock_memory_enricher:
            ctx = AppContext(settings, "test_persona")
            # MemoryEnricher should have been instantiated
            mock_memory_enricher.assert_called_once()
            ctx.close()

    def test_session_event_recorder_failure_swallowed(self, tmp_path):
        """When SessionEventRecorder.start() fails, warning is logged (lines 160-165)."""
        from nous.application.use_cases import AppContext
        from nous.config.settings import Settings

        settings = Settings(data_root=str(tmp_path))

        with patch("nous.application.session_event_recorder.SessionEventRecorder") as mock_session_event_recorder:
            # Make start() raise
            instance = MagicMock()
            instance.start.side_effect = RuntimeError("recorder init failed")
            mock_session_event_recorder.return_value = instance

            ctx = AppContext(settings, "test_persona")
            # Should not raise
            assert ctx._session_event_recorder is None
            ctx.close()

    def test_embedding_model_init_and_access(self, tmp_path):
        """embedding_model is eagerly created in __init__ for pre-warming (lines 168-179)."""
        from nous.application.use_cases import AppContext
        from nous.config.settings import Settings

        settings = Settings(data_root=str(tmp_path))

        # Patch _init_vector_store to avoid eager vector store creation
        with patch.object(AppContext, "_init_vector_store", return_value=None):
            ctx = AppContext(settings, "test_persona")
            # After init, _embedding is immediately created for background preloading
            assert ctx._embedding is not None

            # Access embedding_model property — returns the same instance
            emb = ctx.embedding_model
            assert emb is ctx._embedding
            # Second access returns cached
            emb2 = ctx.embedding_model
            assert emb2 is ctx._embedding

            ctx.close()


class TestAppContextRegistry:
    """Tests for AppContextRegistry class methods."""

    def test_get_creates_settings_if_not_configured(self, tmp_path):
        """When _settings is None, get() should create default Settings (lines 229-231)."""
        from nous.application.use_cases import AppContextRegistry

        # Ensure _settings is None
        AppContextRegistry._settings = None
        AppContextRegistry._contexts.clear()

        with (
            patch.object(AppContextRegistry, "_settings", None),
            patch("nous.config.settings.Settings") as mock_settings,
            patch("nous.application.use_cases.AppContext") as mock_app_context,
        ):
            mock_settings_inst = MagicMock()
            mock_settings_inst.data_dir = str(tmp_path)
            mock_settings.return_value = mock_settings_inst

            mock_ctx = MagicMock()
            mock_app_context.return_value = mock_ctx

            ctx = AppContextRegistry.get("test_persona")
            mock_settings.assert_called_once()
            assert ctx is mock_ctx

        # Clean up
        AppContextRegistry._contexts.clear()

    def test_get_returns_cached_context(self, tmp_path):
        """get() should return the same context for the same persona."""
        from nous.application.use_cases import AppContextRegistry

        AppContextRegistry._settings = None
        AppContextRegistry._contexts.clear()

        mock_ctx = MagicMock()
        AppContextRegistry._contexts["test"] = mock_ctx

        ctx = AppContextRegistry.get("test")
        assert ctx is mock_ctx

        AppContextRegistry._contexts.clear()

    def test_close_all_closes_and_clears(self):
        """close_all should close all contexts and clear the registry."""
        from nous.application.use_cases import AppContextRegistry

        AppContextRegistry._contexts.clear()
        ctx1 = MagicMock()
        ctx2 = MagicMock()
        AppContextRegistry._contexts["a"] = ctx1
        AppContextRegistry._contexts["b"] = ctx2

        AppContextRegistry.close_all()
        ctx1.close.assert_called_once()
        ctx2.close.assert_called_once()
        assert AppContextRegistry._contexts == {}


class TestAppContextVectorStore:
    """Tests for AppContext.vector_store property edge cases."""

    def test_vector_store_init_failure_returns_none(self, tmp_path):
        """When QdrantClientManager init fails, vector_store returns None (lines 177-178)."""
        from nous.application.use_cases import AppContext
        from nous.config.settings import Settings

        settings = Settings(data_root=str(tmp_path))

        with patch("nous.application.use_cases.QdrantClientManager") as mock_qdrant_client_manager:
            # Make QdrantClientManager raise
            mock_qdrant_client_manager.side_effect = RuntimeError("Qdrant unavailable")

            ctx = AppContext(settings, "test_persona")
            result = ctx.vector_store
            assert result is None
            ctx.close()

    def test_vector_store_init_success(self, tmp_path):
        """When Qdrant is available, vector_store is initialized (lines 174-176)."""
        from nous.application.use_cases import AppContext
        from nous.config.settings import Settings

        settings = Settings(data_root=str(tmp_path), qdrant={"url": "http://localhost:6333"})

        with (
            patch("nous.application.use_cases.QdrantClientManager") as mock_qdrant_client_manager,
            patch("nous.application.use_cases.QdrantVectorStore") as mock_vector_store,
            patch.object(MagicMock(), "embedding_model", create=True),
            patch.object(AppContext, "_init_vector_store", return_value=None),
        ):
            mock_mgr = AsyncMock()
            mock_mgr.connect = AsyncMock(return_value=mock_mgr)
            mock_mgr.health_check = AsyncMock(return_value=True)
            mock_qdrant_client_manager.return_value = mock_mgr

            mock_vs = MagicMock()
            mock_vector_store.return_value = mock_vs
            mock_vs.ensure_collection = AsyncMock(return_value=Success(None))

            ctx = AppContext(settings, "test_persona")
            # Access vector_store to trigger lazy init
            result = ctx.vector_store
            assert result is mock_vs
            mock_vs.ensure_collection.assert_called_once_with("test_persona")
            ctx.close()

    def test_vector_store_health_check_false(self, tmp_path):
        """When health_check returns False, vector_store stays None."""
        from nous.application.use_cases import AppContext
        from nous.config.settings import Settings

        settings = Settings(data_root=str(tmp_path), qdrant={"url": "http://localhost:6333"})

        with patch("nous.application.use_cases.QdrantClientManager") as mock_qdrant_client_manager:
            mock_mgr = AsyncMock()
            mock_mgr.connect = AsyncMock(return_value=mock_mgr)
            mock_mgr.health_check = AsyncMock(return_value=False)
            mock_qdrant_client_manager.return_value = mock_mgr

            ctx = AppContext(settings, "test_persona")
            result = ctx.vector_store
            assert result is None
            ctx.close()

    @pytest.mark.asyncio
    async def test_search_engine_strength_lookup_fallback_to_default(self, tmp_path):
        """When get_strength fails, strength_lookup defaults to 1.0 (line 197)."""
        from nous.application.use_cases import AppContext
        from nous.config.settings import Settings

        settings = Settings(data_root=str(tmp_path))

        ctx = AppContext(settings, "test_persona")

        # Make get_strength return Failure → _strength_lookup falls to return 1.0
        ctx.memory_repo.get_strength = MagicMock(return_value=Failure(Exception("not found")))

        from nous.domain.search.engine import SearchQuery

        # Use hybrid mode which goes through the ranker.
        # vector_store must be None so QdrantSemanticSearch is not created (it would fail).
        # The search engine then uses only keyword results + ranker.
        with patch.object(ctx, "_vector_store", None):
            se = ctx.search_engine
            mem = MagicMock(
                key="test_key", importance=0.5, created_at=MagicMock(), content="test content", tags=["test"]
            )
            se._keyword.search = MagicMock(return_value=Success([(mem, 1.0)]))
            result = await se.search(SearchQuery(text="test", top_k=5, mode="hybrid"))
            assert result.is_ok

        ctx.close()

    @pytest.mark.asyncio
    async def test_search_engine_strength_lookup_none_strength(self, tmp_path):
        """When get_strength returns Success(None), strength_lookup returns 1.0."""
        from nous.application.use_cases import AppContext
        from nous.config.settings import Settings

        settings = Settings(data_root=str(tmp_path))

        ctx = AppContext(settings, "test_persona")

        # Make get_strength return Success(None) → _strength_lookup falls to return 1.0
        ctx.memory_repo.get_strength = MagicMock(return_value=Success(None))

        from nous.domain.search.engine import SearchQuery

        with patch.object(ctx, "_vector_store", None):
            se = ctx.search_engine
            mem = MagicMock(
                key="test_key", importance=0.5, created_at=MagicMock(), content="test content", tags=["test"]
            )
            se._keyword.search = MagicMock(return_value=Success([(mem, 1.0)]))
            result = await se.search(SearchQuery(text="test", top_k=5, mode="hybrid"))
            assert result.is_ok

        ctx.close()
