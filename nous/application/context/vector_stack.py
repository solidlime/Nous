"""Vector stack: embedding / reranker / Qdrant store / search engine (責務3+5ベクトル系).

AppContext（composition root の facade）が継承する mixin。
初期化・プロパティ・ベクトル同期イベント購読の実装本体を担う。

状態属性（_vector_store, _embedding, _reranker, _search_engine,
_vector_store_lock/_ready/_init_started）は AppContext のインスタンス上に
保持される（テストが直接代入する互換属性でもある）。
"""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import TYPE_CHECKING

from nous.domain.search.engine import SearchEngine, invalidate_query_cache
from nous.domain.search.ranker import (
    ChainedRanker,
    EmotionRecallBiasRanker,
    ForgettingCurveRanker,
    RRFRanker,
    TopicAffinityRanker,
)
from nous.domain.shared.result import Failure, Success
from nous.infrastructure.embedding.model import EmbeddingModel

if TYPE_CHECKING:
    from nous.config.settings import Settings
    from nous.domain.memory.graph import EntityService
    from nous.domain.memory.service import MemoryService
    from nous.infrastructure.embedding.reranker import RerankerModel
    from nous.infrastructure.qdrant.adapter import QdrantVectorStore
    from nous.infrastructure.sqlite.entity_repo import SQLiteEntityRepository
    from nous.infrastructure.sqlite.memory_repo import SQLiteMemoryRepository

logger = logging.getLogger(__name__)


class VectorStackMixin:
    """ベクトル検証スタックの実装（責務3 + 5のベクトル系イベント購読）。"""

    if TYPE_CHECKING:
        # ホスト（AppContext）が提供する属性の型宣言（mixin 公式パターン）。
        settings: Settings
        persona: str
        memory_repo: SQLiteMemoryRepository
        entity_repo: SQLiteEntityRepository
        entity_service: EntityService
        memory_service: MemoryService
        _vector_store: QdrantVectorStore | None
        _vector_store_lock: threading.Lock
        _vector_store_ready: threading.Event
        _vector_store_init_started: bool
        _embedding: EmbeddingModel | None
        _reranker: RerankerModel | None
        _search_engine: SearchEngine | None

    # ------------------------------------------------------------------
    # 初期化（旧 _init_vector / _preload_background の本体）
    # ------------------------------------------------------------------

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

        reranker = RerankerModel(
            model_name=self.settings.reranker.model,
            enabled=self.settings.reranker.enabled,
        )
        self._reranker = reranker

        # EmbeddingModel (eager init; preload thread launched in _preload_background)
        embedding = EmbeddingModel(config=self.settings.embedding)
        self._embedding = embedding

    def _preload_background(self) -> None:
        """Start background daemon threads for model preloading and warmup.

        Depends on: _init_vector (self._reranker, self._embedding),
        _init_storage (self.memory_repo, etc.), _init_services (self.event_bus).
        All threads are daemon — they never block shutdown.
        """
        # 1. Reranker model preload
        reranker = self._reranker
        if reranker is not None and reranker.enabled:
            import threading

            def _safe_preload() -> None:
                try:
                    reranker._load_model()
                except Exception:
                    logger.warning("Reranker preload failed (will lazy-load on first use)", exc_info=True)

            threading.Thread(target=_safe_preload, daemon=True).start()

        # 2. Embedding model preload
        import threading as _embed_threading

        embedding = self._embedding
        if embedding is not None:

            def _preload_embedding() -> None:
                try:
                    embedding._ensure_loaded()
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

    # ------------------------------------------------------------------
    # 公開プロパティ（旧 AppContext のプロパティ本体）
    # ------------------------------------------------------------------

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
            from nous.application.use_cases import QdrantSemanticSearch, SQLiteKeywordSearch

            keyword = SQLiteKeywordSearch(self.memory_repo)
            vector_store = self._vector_store
            semantic = QdrantSemanticSearch(vector_store, self.memory_repo) if vector_store else None

            def _strength_lookup(key: str) -> tuple[float, float] | None:
                result = self.memory_repo.get_strength(key)
                if isinstance(result, Success) and result.value is not None:
                    return (result.value.strength, result.value.stability)
                return None

            ranker = ChainedRanker(
                RRFRanker(),
                ForgettingCurveRanker(_strength_lookup),
                EmotionRecallBiasRanker(),
                TopicAffinityRanker(),
            )
            search_engine = SearchEngine(
                keyword,
                semantic,
                ranker,
                memory_repo=self.memory_repo,
                reranker=self._reranker,
                entity_service=self.entity_service,
                link_repo=self.entity_repo,
                # embedding_model property は呼ばない（cold load 防止）:
                # rank_policy 段が要求した時点で lazy に解決する。
                embedding_provider=lambda: getattr(self, "_embedding", None),
            )
            # worker 経路ではハンドラの set_persona が走らないため、生成時に必ず伝播させる
            search_engine.set_persona(self.persona)
            # Wire search engine to memory service for memory evolution
            self.memory_service.set_search_engine(search_engine)
            self._search_engine = search_engine
        return self._search_engine

    # ------------------------------------------------------------------
    # Vector store initialization（旧 _init_vector_store / _init_vector_store_async の本体）
    # ------------------------------------------------------------------

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
        # QdrantClientManager / QdrantVectorStore は use_cases モジュール経由で
        # 解決する（既存テストが nous.application.use_cases 名前空間を patch して
        # 差し替えるため。直接 import だと差し替え対象が変わってしまう）。
        from nous.application import use_cases

        try:
            mgr = use_cases.QdrantClientManager(self.settings.qdrant.url, self.settings.qdrant.api_key)
            await mgr.connect()
            if await mgr.health_check():
                emb = self.embedding_model
                vs = use_cases.QdrantVectorStore(mgr, emb, self.settings.qdrant.collection_prefix)
                result = await vs.ensure_collection(self.persona)
                if isinstance(result, Failure):
                    logger.warning(
                        "VectorStore collection creation failed for '%s': %s",
                        self.persona,
                        result.error,
                    )
                    return None
                return vs
        except Exception as _e:
            logger.debug("VectorStore async init failed (Qdrant unavailable?): %s", _e)
        return None

    # ------------------------------------------------------------------
    # Vector store sync event handlers（旧 AppContext のハンドラ本体）
    # ------------------------------------------------------------------

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
            if isinstance(mem_result, Success) and mem_result.value is not None:
                # Never resurrect tombstoned memories into the vector store
                if getattr(mem_result.value, "lifecycle_status", "active") == "tombstoned":
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
