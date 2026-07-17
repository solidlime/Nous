from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from nous.domain.equipment.service import EquipmentService
from nous.domain.memory.service import MemoryService
from nous.domain.persona.service import PersonaService
from nous.domain.search.engine import SearchEngine
from nous.domain.search.ranker import (
    ChainedRanker,
    EmotionRecallBiasRanker,
    ForgettingCurveRanker,
    RRFRanker,
    TopicAffinityRanker,
)
from nous.domain.shared.errors import SearchError
from nous.domain.shared.result import Failure, Success
from nous.infrastructure.embedding.model import EmbeddingModel
from nous.infrastructure.qdrant.adapter import QdrantVectorStore
from nous.infrastructure.qdrant.client import QdrantClientManager
from nous.infrastructure.sqlite.connection import SQLiteConnection
from nous.infrastructure.sqlite.entity_repo import SQLiteEntityRepository
from nous.infrastructure.sqlite.equipment_repo import SQLiteEquipmentRepository
from nous.infrastructure.sqlite.memory_repo import SQLiteMemoryRepository
from nous.infrastructure.sqlite.persona_repo import SQLitePersonaRepository

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from nous.config.settings import Settings
    from nous.infrastructure.embedding.reranker import RerankerModel


class SQLiteKeywordSearch:
    """Adapter: SQLiteMemoryRepository -> KeywordSearchStrategy Protocol."""

    def __init__(self, repo: SQLiteMemoryRepository) -> None:
        self.repo = repo

    def search(self, query: str, limit: int = 10, date_from=None, date_to=None):
        result = self.repo.search_keyword(query, limit, date_from=date_from, date_to=date_to)
        if result.is_ok:
            return Success(result.value)
        return Failure(SearchError(str(result.error)))


class QdrantSemanticSearch:
    """Adapter: QdrantVectorStore -> SemanticSearchStrategy Protocol."""

    def __init__(self, vector_store: QdrantVectorStore, memory_repo: SQLiteMemoryRepository) -> None:
        self.vector_store = vector_store
        self.memory_repo = memory_repo
        self.persona: str = ""

    async def search(self, query: str, limit: int = 10, date_from=None, date_to=None):
        # Fetch extra results to compensate for date post-filtering
        fetch_limit = limit * 3 if (date_from or date_to) else limit
        result = await self.vector_store.search(self.persona, query, fetch_limit)
        if not result.is_ok:
            return Failure(SearchError(str(result.error)))

        search_results: list[tuple] = []
        for key, score in result.value:
            mem_result = self.memory_repo.find_by_key(key)
            if mem_result.is_ok and mem_result.value:
                memory = mem_result.value
                # Post-filter by date range
                if date_from or date_to:
                    created = memory.created_at
                    # Strip timezone from filter bounds for naive comparison.
                    # date_from/date_to from parse_date_range are JST-aware,
                    # but memory.created_at from SQLite is timezone-naive.
                    if date_from and created < date_from.replace(tzinfo=None):
                        continue
                    if date_to and created > date_to.replace(tzinfo=None):
                        continue
                search_results.append((memory, score))
                if len(search_results) >= limit:
                    break
        return Success(search_results)


class AppContext:
    """Dependency injection container for the application."""

    def __init__(self, settings: Settings, persona: str) -> None:
        self.settings = settings
        self.persona = persona
        self.connection = SQLiteConnection(settings.data_dir, persona)
        try:
            self.connection.initialize_schema()
        except Exception as e:
            logging.getLogger("nous").warning("Schema initialization failed for persona '%s': %s", persona, e)
            # Continue - migration will attempt repair, and if it also fails,
            # AppContext will still be created but functionality may be degraded

        # Repositories
        self.memory_repo = SQLiteMemoryRepository(self.connection)
        self.persona_repo = SQLitePersonaRepository(self.connection)
        self.equipment_repo = SQLiteEquipmentRepository(self.connection)
        self.entity_repo = SQLiteEntityRepository(self.connection)

        # Entity graph (optional — never blocks core memory operations)
        # Must be initialized before MemoryService so it can be injected
        from nous.domain.memory.graph import EntityService

        self.entity_service = EntityService(self.entity_repo)

        # Create MemoryEnricher if configured (best-effort enrichment)
        enricher = None
        if self.settings.memory_enrichment.enabled:
            api_key = self.settings.memory_enrichment.get_effective_api_key(self.settings)
            if api_key:
                from nous.infrastructure.llm.memory_enricher import (
                    MemoryEnricher,
                )

                enricher = MemoryEnricher(
                    provider=self.settings.memory_enrichment.provider,
                    api_key=api_key,
                    model=self.settings.memory_enrichment.model,
                    base_url=self.settings.memory_enrichment.base_url,
                    min_chars=self.settings.memory_enrichment.min_chars,
                )

        # EventBus (must be created before services)
        from nous.application.event_bus import EventBus

        self.event_bus = EventBus()

        # Services
        self.memory_service = MemoryService(
            self.memory_repo,
            entity_service=self.entity_service,
            enricher=enricher,
        )
        self.persona_service = PersonaService(self.persona_repo, event_bus=self.event_bus)
        self.equipment_service = EquipmentService(self.equipment_repo)

        # Vector store (lazy)
        self._vector_store: QdrantVectorStore | None = None
        self._embedding: EmbeddingModel | None = None
        self._reranker: RerankerModel | None = None
        self._search_engine: SearchEngine | None = None

        # Instantiate reranker model
        from nous.infrastructure.embedding.reranker import RerankerModel

        self._reranker = RerankerModel(
            model_name=self.settings.reranker.model,
            enabled=self.settings.reranker.enabled,
        )

        # Preload reranker model in background thread (avoid blocking first search)
        if self._reranker.enabled:
            import threading

            def _safe_preload() -> None:
                try:
                    self._reranker._load_model()
                except Exception:
                    logger.debug("Reranker preload failed (will lazy-load on first use)")

            threading.Thread(target=_safe_preload, daemon=True).start()

        # Initialize SessionEventRecorder (best-effort, don't fail startup)
        try:
            from nous.application.session_event_recorder import SessionEventRecorder
            from nous.infrastructure.sqlite.session_event_repo import SessionEventRepository

            self._session_event_repo = SessionEventRepository(self.connection)
            self._session_event_recorder = SessionEventRecorder(self.event_bus, self._session_event_repo)
            self._session_event_recorder.start()
        except Exception as e:
            import logging as _logging

            _logging.getLogger("nous").warning("SessionEventRecorder init failed: %s", e)
            self._session_event_repo = None
            self._session_event_recorder = None

        # Kick off vector store init in background thread to avoid blocking
        # persona creation / startup (Qdrant may be unavailable or slow).
        # The vector_store property handles lazy-init on first access.
        import threading as _threading

        _threading.Thread(target=self._init_vector_store, daemon=True).start()

    @property
    def vector_store(self) -> QdrantVectorStore | None:
        """Lazy-init vector store. Returns None if Qdrant unavailable or collection creation fails."""
        if self._vector_store is None:
            try:
                asyncio.get_running_loop()
                # Running inside an event loop — cannot block here.
                # Caller should use await ctx._init_vector_store_async() explicitly.
            except RuntimeError:
                # No running loop — safe to call asyncio.run()
                try:
                    result = asyncio.run(self._init_vector_store_async())
                    if result is not None:
                        self._vector_store = result
                except Exception as _e:
                    logger.debug("VectorStore init failed (Qdrant unavailable?): %s", _e)
        return self._vector_store

    @property
    def embedding_model(self) -> EmbeddingModel:
        if self._embedding is None:
            self._embedding = EmbeddingModel(self.settings.embedding)
        return self._embedding

    @property
    def search_engine(self) -> SearchEngine:
        if self._search_engine is None:
            keyword = SQLiteKeywordSearch(self.memory_repo)
            semantic = QdrantSemanticSearch(self.vector_store, self.memory_repo) if self.vector_store else None

            def _strength_lookup(key: str) -> tuple[float, float] | None:
                result = self.memory_repo.get_strength(key)
                if result.is_ok and result.value is not None:
                    return (result.value.strength, result.value.stability)
                return None

            ranker = ChainedRanker(
                RRFRanker(),
                ForgettingCurveRanker(_strength_lookup),
                EmotionRecallBiasRanker(),
                TopicAffinityRanker(),
            )
            self._search_engine = SearchEngine(
                keyword,
                semantic,
                ranker,
                memory_repo=self.memory_repo,
                memorag_config=self.settings.memorag,
                reranker=self._reranker,
                entity_service=self.entity_service,
            )
            # Wire search engine to memory service for memory evolution
            self.memory_service._search_engine = self._search_engine
        return self._search_engine

    def _init_vector_store(self) -> None:
        """Eagerly ensure Qdrant collection exists for this persona on startup.

        Called from a daemon thread (AppContext.__init__), so asyncio.run() is safe here.
        """
        result = asyncio.run(self._init_vector_store_async())
        if result is not None:
            self._vector_store = result

    async def _init_vector_store_async(self) -> QdrantVectorStore | None:
        """Async vector store initialization (connect + ensure collection)."""
        try:
            mgr = QdrantClientManager(self.settings.qdrant.url, self.settings.qdrant.api_key)
            await mgr.connect()
            if await mgr.health_check():
                emb = self.embedding_model
                vs = QdrantVectorStore(mgr, emb, self.settings.qdrant.collection_prefix)
                result = await vs.ensure_collection(self.persona)
                if result.is_ok:
                    return vs
                logger.warning(
                    "VectorStore collection creation failed for '%s': %s",
                    self.persona,
                    result.error,
                )
        except Exception as _e:
            logger.debug("VectorStore async init failed (Qdrant unavailable?): %s", _e)
        return None

    async def close_async(self) -> None:
        """Async close: release Qdrant connection and SQLite connection."""
        if self._vector_store is not None:
            await self._vector_store.client_manager.close()
        self.connection.close()

    def close(self) -> None:
        self.connection.close()


class AppContextRegistry:
    """Registry managing per-persona AppContext instances."""

    _contexts: dict[str, AppContext] = {}
    _settings: Settings | None = None

    @classmethod
    def configure(cls, settings: Settings) -> None:
        cls._settings = settings

    @classmethod
    def get(cls, persona: str) -> AppContext:
        if persona in cls._contexts:
            return cls._contexts[persona]

        if cls._settings is None:
            from nous.config.settings import Settings

            cls._settings = Settings()

        ctx = AppContext(cls._settings, persona)
        cls._contexts[persona] = ctx

        if cls._settings.forgetting.enabled:
            from nous.application.workers.decay_worker import DecayWorker

            decay_worker = DecayWorker(ctx, cls._settings.forgetting.decay_interval_seconds)
            decay_worker.start()

        return ctx

    @classmethod
    def close_all(cls) -> None:
        for ctx in cls._contexts.values():
            ctx.close()
        cls._contexts.clear()
