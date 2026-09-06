from __future__ import annotations

import asyncio
import logging
import threading
from pathlib import Path
from typing import TYPE_CHECKING

from nous.domain.equipment.service import EquipmentService
from nous.domain.memory.service import MemoryService
from nous.domain.persona.service import PersonaService
from nous.domain.search.engine import SearchEngine, invalidate_query_cache
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
    from nous.application.workers.decay_worker import DecayWorker
    from nous.application.workers.enrichment_worker import EnrichmentWorker
    from nous.config.settings import Settings
    from nous.domain.chat_config import ChatConfig
    from nous.infrastructure.embedding.reranker import RerankerModel


class SQLiteKeywordSearch:
    """Adapter: SQLiteMemoryRepository -> KeywordSearchStrategy Protocol."""

    def __init__(self, repo: SQLiteMemoryRepository) -> None:
        self.repo = repo

    def search(self, query: str, limit: int = 10, date_from=None, date_to=None, tags=None):
        result = self.repo.search_keyword(query, limit, date_from=date_from, date_to=date_to, tags=tags)
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
                # Exclude tombstoned memories (vector points may linger)
                if getattr(memory, "lifecycle_status", "active") == "tombstoned":
                    continue
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

    def __init__(self, settings: Settings, persona: str, config: ChatConfig | None = None) -> None:
        self.settings = settings
        self.persona = persona
        self._config = config
        self._current_session_id: str | None = None
        # In-memory Hebbian co-access tracker: keys of memories read/created
        # in this session (rolling window, most recent last).  Volatile by
        # design — Hebbian links rebuild progressively, so nothing is lost.
        self._coaccess_keys: list[str] = []
        self._init_storage()
        self._init_enricher()
        self._init_services()
        self._init_vector()
        self._preload_background()

    @property
    def session_id(self) -> str | None:
        """Current chat session ID, set by ChatService.chat().

        Used by MCP tools to propagate session context to
        MemoryLinkService for Hebbian co-activation linking.
        """
        return self._current_session_id

    @session_id.setter
    def session_id(self, value: str | None) -> None:
        self._current_session_id = value

    def record_memory_access(self, key: str) -> None:
        """Record a memory key in the Hebbian co-access tracker.

        Rolling window of the last 20 keys (most recent last); duplicates are
        moved to the end so repeated reads keep recency.  Best-effort: never
        raises into the caller (MCP tool flow).
        """
        if not key:
            return
        try:
            if key in self._coaccess_keys:
                self._coaccess_keys.remove(key)
            self._coaccess_keys.append(key)
            del self._coaccess_keys[:-20]
        except Exception:
            logger.debug("record_memory_access failed for %s", key, exc_info=True)

    # ------------------------------------------------------------------
    # Private factory methods (called in order from __init__)
    # ------------------------------------------------------------------

    def _init_storage(self) -> None:
        """Initialize SQLite connection, repositories, and entity service.

        Must run first — downstream methods depend on connection and repos.
        """
        self.connection = SQLiteConnection(self.settings.persona_dir, self.persona)
        try:
            self.connection.initialize_schema()
        except Exception:
            logging.getLogger("nous").exception("Schema initialization failed for persona '%s'", self.persona)
            # Continue - migration will attempt repair, and if it also fails,
            # AppContext will still be created but functionality may be degraded

        # Repositories
        self.memory_repo = SQLiteMemoryRepository(self.connection)
        self.persona_repo = SQLitePersonaRepository(self.connection)
        self.equipment_repo = SQLiteEquipmentRepository(self.connection)
        self.entity_repo = SQLiteEntityRepository(self.connection)

        # Persistent enrichment queue (drained by EnrichmentWorker when idle)
        from nous.infrastructure.sqlite.enrichment_queue_repo import EnrichmentQueueRepository

        self.enrichment_queue = EnrichmentQueueRepository(self.connection)

        # Entity graph (optional — never blocks core memory operations)
        # Must be initialized before MemoryService so it can be injected
        from nous.domain.memory.graph import EntityService

        self.entity_service = EntityService(self.entity_repo)

    def _init_enricher(self) -> None:
        """Resolve LLM provider settings and create MemoryEnricher if configured.

        Depends on: _init_storage (self._config, self.settings).
        Best-effort; failure results in enricher=None (logged as debug).
        """
        enricher: MemoryEnricher | None = None
        cfg = self._config
        mem_enrich_enabled = cfg.memory_enrichment_enabled if cfg else self.settings.memory_enrichment.enabled
        if mem_enrich_enabled:
            # Use global MemoryEnrichmentConfig for provider/base_url/min_chars;
            # model can be overridden via session config.
            provider = self.settings.memory_enrichment.provider
            base_url = self.settings.memory_enrichment.base_url
            min_chars = self.settings.memory_enrichment.min_chars
            if cfg:
                model = cfg.memory_enrichment_model or self.settings.memory_enrichment.model
                api_key = ""
                if provider == "openrouter":
                    api_key = self.settings.openrouter_api_key
                elif provider == "anthropic":
                    api_key = self.settings.anthropic_api_key
                elif provider == "openai":
                    api_key = self.settings.openai_api_key
                elif provider == "google":
                    api_key = self.settings.google_api_key
                elif provider == "opencode_go":
                    api_key = self.settings.opencode_go_api_key
                if not api_key:
                    from nous.config.runtime_config import RuntimeConfigManager

                    key_name = f"{provider}_api_key"
                    value, _ = RuntimeConfigManager().get_effective_value("api_keys", key_name)
                    api_key = value or ""
            else:
                api_key = self.settings.memory_enrichment.get_effective_api_key(self.settings)
                model = self.settings.memory_enrichment.model
            if api_key:
                from nous.infrastructure.llm.memory_enricher import MemoryEnricher

                enricher = MemoryEnricher(
                    provider=provider,
                    api_key=api_key,
                    model=model,
                    base_url=base_url,
                    min_chars=min_chars,
                )
        self._enricher = enricher

    def _init_services(self) -> None:
        """Create EventBus and all domain services.

        Depends on: _init_storage (repos, entity_service), _init_enricher (self._enricher).
        """
        # EventBus (must be created before services)
        from nous.application.event_bus import EventBus

        self.event_bus = EventBus()

        # Initialize SessionEventRepository before MemoryService so it can
        # be injected for Hebbian co-activation linking (D5/N6 fix).
        try:
            from nous.infrastructure.sqlite.session_event_repo import SessionEventRepository

            self._session_event_repo = SessionEventRepository(self.connection)
        except Exception as e:
            import logging as _logging

            _logging.getLogger("nous").warning("SessionEventRepository init failed: %s", e)
            self._session_event_repo = None

        # Services
        self.memory_service = MemoryService(
            self.memory_repo,
            entity_service=self.entity_service,
            enricher=self._enricher,
            link_repo=self.entity_repo,
            coaccess_tracker=self._coaccess_keys,
            enrichment_queue=self.enrichment_queue,
        )
        self.persona_service = PersonaService(
            self.persona_repo, event_bus=self.event_bus, memory_service=self.memory_service
        )
        self.equipment_service = EquipmentService(self.equipment_repo)

        # Vector store sync via event handlers (replaces direct calls from MCP tools)
        self.event_bus.subscribe("memory.created", self._on_memory_vector_upsert)
        self.event_bus.subscribe("memory.updated", self._on_memory_vector_upsert)
        self.event_bus.subscribe("memory.deleted", self._on_memory_vector_delete)

        # Invalidate the query cache on writes so new data is immediately searchable
        self.event_bus.subscribe("memory.created", self._on_memory_cache_invalidate)
        self.event_bus.subscribe("memory.updated", self._on_memory_cache_invalidate)
        self.event_bus.subscribe("memory.deleted", self._on_memory_cache_invalidate)

        # Initialize SessionEventRecorder (best-effort, don't fail startup)
        # Uses self._session_event_repo already created in _init_services above.
        try:
            from nous.application.session_event_recorder import SessionEventRecorder

            self._session_event_recorder = SessionEventRecorder(self.event_bus, self._session_event_repo)
            self._session_event_recorder.start()
        except Exception as e:
            import logging as _logging

            _logging.getLogger("nous").warning("SessionEventRecorder init failed: %s", e)
            self._session_event_repo = None
            self._session_event_recorder = None

    def _init_vector(self) -> None:
        """Initialize embedding model, reranker, and vector store placeholders.

        Depends on: _init_storage (self.settings).
        Models are instantiated here; background preloading happens in _preload_background.
        """
        # Vector store (lazy, exactly-once init guarded by lock + event)
        self._vector_store: QdrantVectorStore | None = None
        self._vector_store_lock = threading.Lock()
        self._vector_store_ready = threading.Event()
        self._vector_store_init_started = False
        self._embedding: EmbeddingModel | None = None
        self._reranker: RerankerModel | None = None
        self._search_engine: SearchEngine | None = None

        # Instantiate reranker model
        from nous.infrastructure.embedding.reranker import RerankerModel

        self._reranker = RerankerModel(
            model_name=self.settings.reranker.model,
            enabled=self.settings.reranker.enabled,
        )

        # EmbeddingModel (eager init; preload thread launched in _preload_background)
        self._embedding = EmbeddingModel(config=self.settings.embedding)

    def _preload_background(self) -> None:
        """Start background daemon threads for model preloading and warmup.

        Depends on: _init_vector (self._reranker, self._embedding),
        _init_storage (self.memory_repo, etc.), _init_services (self.event_bus).
        All threads are daemon — they never block shutdown.
        """
        # 1. Reranker model preload
        if self._reranker.enabled:
            import threading

            def _safe_preload() -> None:
                try:
                    self._reranker._load_model()
                except Exception:
                    logger.warning("Reranker preload failed (will lazy-load on first use)", exc_info=True)

            threading.Thread(target=_safe_preload, daemon=True).start()

        # 2. Embedding model preload
        import threading as _embed_threading

        def _preload_embedding() -> None:
            try:
                self._embedding._ensure_loaded()
            except Exception:
                logger.warning("EmbeddingModel preload failed (will lazy-load on first use)", exc_info=True)

        _embed_threading.Thread(target=_preload_embedding, daemon=True).start()

        # 3. Sudachi dictionary preload (lazy-download on first use otherwise)
        import threading

        def _safe_preload_sudachi() -> None:
            try:
                from nous.domain.memory.sudachi_extractor import SudachiExtractor

                # Trigger dict download by creating instance and calling extract
                SudachiExtractor().extract("")
                logger.debug("Sudachi dictionary preloaded successfully")
            except Exception:
                logger.warning("Sudachi preload failed (will retry on first use)", exc_info=True)

        threading.Thread(target=_safe_preload_sudachi, daemon=True).start()

        # 4. Vector store background init (Qdrant may be unavailable or slow)
        # The vector_store property handles lazy-init on first access.
        import threading as _threading

        _threading.Thread(target=self._init_vector_store, daemon=True).start()

        # 5. SearchEngine background warmup (reduce latency on first search)
        def _warmup_search_engine() -> None:
            try:
                _ = self.search_engine  # プロパティアクセスで全戦略を初期化
                logger.debug("SearchEngine warmed up")
            except Exception:
                logger.warning("SearchEngine warmup failed (will init on first use)", exc_info=True)

        _threading.Thread(target=_warmup_search_engine, daemon=True).start()

    @property
    def config(self) -> ChatConfig | None:
        """Per-request chat config (None if AppContext created without one)."""
        return self._config

    @property
    def vector_store(self) -> QdrantVectorStore | None:
        """Lazy-init vector store. Returns None if Qdrant unavailable or collection creation fails."""
        if self._vector_store is None:
            try:
                asyncio.get_running_loop()
                # Running inside an event loop — cannot block here.
                # Caller should use await ctx._init_vector_store_async() explicitly.
            except RuntimeError:
                # No running loop — safe to block on the guarded init.
                self._init_vector_store()
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
                reranker=self._reranker,
                entity_service=self.entity_service,
                link_repo=self.entity_repo,
            )
            # Wire search engine to memory service for memory evolution
            self.memory_service.set_search_engine(self._search_engine)
        return self._search_engine

    def _init_vector_store(self) -> None:
        """Ensure Qdrant collection exists for this persona — exactly once.

        Called from a daemon thread (AppContext.__init__) and lazily from the
        vector_store property. The lock guarantees only one caller runs the
        async init; the event unblocks the others once it completes.
        """
        with self._vector_store_lock:
            if self._vector_store_init_started:
                started_elsewhere = True
            else:
                self._vector_store_init_started = True
                started_elsewhere = False
        if started_elsewhere:
            self._vector_store_ready.wait()
            return
        try:
            result = asyncio.run(self._init_vector_store_async())
            if result is not None:
                self._vector_store = result
        finally:
            self._vector_store_ready.set()

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
        # Unblock any waiter on an init that will never complete (daemon thread died, etc.)
        self._vector_store_ready.set()

    # ── Vector store sync event handlers ──

    async def _on_memory_vector_upsert(self, event_type: str, data: dict) -> None:
        """Sync memory to vector store when created or updated.

        Best-effort: failures are logged as warnings and never interrupt the
        main flow. If vector_store is not yet initialized, the sync is skipped
        (the memory will be indexed on next background init or explicit call).
        """
        if self._vector_store is None:
            return
        try:
            key = data.get("key", "")
            persona = data.get("persona", self.persona)
            mem_result = self.memory_repo.find_by_key(key)
            if mem_result.is_ok and mem_result.value is not None:
                # Never resurrect tombstoned memories into the vector store
                if getattr(mem_result.value, "lifecycle_status", "active") == "tombstoned":  # type: ignore[union-attr]
                    logger.debug("Vector sync skipped (tombstoned): %s", key)
                    return
                await self._vector_store.upsert(persona, key, mem_result.value.content)
            else:
                logger.warning("Vector sync: memory not found for key: %s", key)
        except Exception:
            logger.warning("Vector sync failed for memory: %s", data.get("key", "?"), exc_info=True)

    async def _on_memory_vector_delete(self, event_type: str, data: dict) -> None:
        """Delete memory vector when tombstoned.

        Best-effort: failures are logged as warnings.
        """
        if self._vector_store is None:
            return
        try:
            key = data.get("key", "")
            persona = data.get("persona", self.persona)
            await self._vector_store.delete(persona, key)
        except Exception:
            logger.warning("Vector delete failed for memory: %s", data.get("key", "?"), exc_info=True)

    async def _on_memory_cache_invalidate(self, event_type: str, data: dict) -> None:
        """Drop cached query results so writes are immediately visible in search."""
        invalidate_query_cache()


class AppContextRegistry:
    """Registry managing per-persona AppContext instances."""

    _contexts: dict[str, AppContext] = {}
    _decay_workers: dict[str, DecayWorker] = {}
    _enrichment_workers: dict[str, EnrichmentWorker] = {}
    _settings: Settings | None = None
    _lock = threading.Lock()

    @classmethod
    def configure(cls, settings: Settings) -> None:
        cls._settings = settings

    @classmethod
    def get(cls, persona: str, config: ChatConfig | None = None) -> AppContext:
        ctx = cls._contexts.get(persona)
        if ctx is not None:
            return ctx

        with cls._lock:
            # 二重チェック: ロック待ち間に他スレッドが生成した場合の重複生成を防ぐ
            ctx = cls._contexts.get(persona)
            if ctx is not None:
                return ctx

            if cls._settings is None:
                from nous.config.settings import Settings

                cls._settings = Settings()

            # パス分離子・親参照を含む persona はディレクトリ存在確認をすり抜けるため拒否
            if not persona or "/" in persona or "\\" in persona or persona in (".", ".."):
                raise ValueError(f"Invalid persona name: '{persona}'")

            persona_root = Path(cls._settings.persona_dir) / persona
            if not persona_root.is_dir():
                raise ValueError(f"Persona '{persona}' not found")

            ctx = AppContext(cls._settings, persona, config=config)
            cls._contexts[persona] = ctx

            forgetting_enabled = config.forgetting_enabled if config else cls._settings.forgetting.enabled
            if forgetting_enabled:
                from nous.application.workers.decay_worker import DecayWorker

                decay_interval = (
                    config.forgetting_decay_interval_seconds
                    if config
                    else cls._settings.forgetting.decay_interval_seconds
                )
                decay_worker = DecayWorker(ctx, decay_interval, config=config)
                decay_worker.start()
                cls._decay_workers[persona] = decay_worker

            # EnrichmentWorker (REM-equivalent): strict `is True` guards so
            # mock settings/configs in tests never start real threads.
            enrichment_enabled = (
                config.memory_enrichment_enabled
                if config
                else getattr(cls._settings.memory_enrichment, "enabled", False)
            ) is True
            brain_auto_run = (
                config.brain_enrich_auto_run if config else getattr(cls._settings.memory_enrichment, "auto_run", False)
            ) is True
            if enrichment_enabled and brain_auto_run:
                from nous.application.workers.enrichment_worker import EnrichmentWorker

                enrichment_worker = EnrichmentWorker(ctx, config)
                enrichment_worker.start()
                cls._enrichment_workers[persona] = enrichment_worker

        return ctx

    @classmethod
    def stop_decay_workers(cls, timeout: float = 5.0) -> None:
        """Stop all decay and enrichment workers (graceful shutdown)."""
        for worker in cls._decay_workers.values():
            worker.stop(timeout=timeout)
        cls._decay_workers.clear()
        for worker in cls._enrichment_workers.values():
            worker.stop(timeout=timeout)
        cls._enrichment_workers.clear()

    @classmethod
    def close_all(cls) -> None:
        for ctx in cls._contexts.values():
            ctx.close()
        cls._contexts.clear()

    @classmethod
    async def close_all_async(cls) -> None:
        """Async close: release Qdrant connections and SQLite connections for all contexts."""
        for ctx in cls._contexts.values():
            await ctx.close_async()
        cls._contexts.clear()
