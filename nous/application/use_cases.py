from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import TYPE_CHECKING

from nous.application.context.event_handlers import EventHandlersMixin
from nous.application.context.lifecycle import LifecycleMixin
from nous.application.context.vector_stack import VectorStackMixin
from nous.domain.equipment.service import EquipmentService
from nous.domain.memory.service import MemoryService
from nous.domain.persona.service import PersonaService
from nous.domain.shared.errors import PersonaNotFoundError, PersonaValidationError, SearchError
from nous.domain.shared.result import Failure, Success
from nous.infrastructure.qdrant.adapter import QdrantVectorStore as QdrantVectorStore  # noqa: TC001

# 後方互換 re-export: vector_stack.py は実行時に use_cases 経由で解決する
# （既存テストが nous.application.use_cases 名前空間を patch して差し替える）。
from nous.infrastructure.qdrant.client import QdrantClientManager  # noqa: F401
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


class AppContext(VectorStackMixin, EventHandlersMixin, LifecycleMixin):
    """Dependency injection container for the application.

    Composition root の facade。責務の実装は nous/application/context/ に分割:
    - VectorStackMixin   : ベクトル検証スタック + ベクトル系イベント購読
    - EventHandlersMixin : tool.called 系ハンドラ + メモリ co-access 追跡
    - LifecycleMixin     : session_id / close 系
    公開属性・メソッド・プロパティ（config, session_id, vector_store,
    embedding_model, search_engine ほか）の名前と意味は不変（呼び出し側互換）。
    """

    def __init__(self, settings: Settings, persona: str, config: ChatConfig | None = None) -> None:
        self.settings = settings
        self.persona = persona
        self._config = config
        self._init_volatile_state()
        self._init_lifecycle_state()
        self._init_storage()
        self._init_enricher()
        self._init_services()
        self._init_vector()
        self._preload_background()

    # ------------------------------------------------------------------
    # config — AppContext 固有の状態（分割対象外）
    # ------------------------------------------------------------------

    @property
    def config(self) -> ChatConfig | None:
        """Per-request chat config (None if AppContext created without one)."""
        return self._config

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

        Resolution chain (single point for the brain-simulator LLM):
        - cfg is None (e.g. MCP-only startup): legacy settings.memory_enrichment chain.
        - brain_llm_dedicated OFF: reuse the chat provider/model/base_url/api_key
          4-piece set verbatim (no mixed provider).
        - brain_llm_dedicated ON: brain_llm_* with the legacy fallback chain;
          the chat api_key is a final fallback ONLY when the brain provider
          matches the chat provider (no key mixing across providers).

        Depends on: _init_storage (self._config, self.settings).
        Best-effort; failure results in enricher=None (logged as debug).
        """
        enricher: MemoryEnricher | None = None
        introspection_engine: IntrospectionEngine | None = None
        cfg = self._config
        mem_enrich_enabled = cfg.memory_enrichment_enabled if cfg else self.settings.memory_enrichment.enabled
        if mem_enrich_enabled:
            min_chars = self.settings.memory_enrichment.min_chars
            if cfg is None:
                provider = self.settings.memory_enrichment.provider
                model = self.settings.memory_enrichment.model
                base_url = self.settings.memory_enrichment.base_url
                api_key = self.settings.memory_enrichment.get_effective_api_key(self.settings)
            elif not cfg.brain_llm_dedicated:
                # OFF: chat 4-piece set.
                p = cfg.provider_config
                provider = p.provider
                model = p.get_effective_model()
                base_url = p.get_effective_base_url()
                api_key = p.get_effective_api_key()
            else:
                # ON: brain_llm_* + legacy fallback chain.
                me = self.settings.memory_enrichment
                provider = cfg.brain_llm_provider or me.provider
                model = cfg.brain_llm_model or me.model
                base_url = cfg.brain_llm_base_url or me.base_url
                api_key = cfg.brain_llm_api_key or self._provider_api_key(provider)
                if not api_key and provider == cfg.provider_config.provider:
                    api_key = cfg.provider_config.get_effective_api_key()
                if not api_key:
                    logger.debug("brain LLM: no api_key for provider '%s'; enrichment disabled", provider)
            if api_key:
                from nous.application.chat.introspection import (
                    IntrospectionEngine,
                    _resolve_brain_llm_params,
                )
                from nous.infrastructure.llm.factory import get_provider
                from nous.infrastructure.llm.memory_enricher import MemoryEnricher

                # params は脳側LLMパラメータ（max_tokens/temperature/reasoning_effort）の
                # 単一解決点（introspection._resolve_brain_llm_params）。None = 呼び出し先既定。
                params = _resolve_brain_llm_params(cfg)

                # OpenCode Go 用の脳側安定セッションID (persona ベース)。persona 未設定なら None
                # (provider 生成側のプロセス既定にフォールバック)。
                brain_session = f"nous-brain-{self.persona}" if getattr(self, "persona", "") else None

                # mypy は **spread の有無から型を窄められない（同一式内の2 spread でも最初の
                # int が無視される）。ponytail: 素直に kwargs 辞書を1つだけ作って渡す。
                brain_kwargs: dict[str, int | float] = {}
                if params.max_tokens is not None:
                    brain_kwargs["max_tokens"] = params.max_tokens
                if params.temperature is not None:
                    brain_kwargs["temperature"] = params.temperature
                enricher = MemoryEnricher(
                    provider=provider,
                    api_key=api_key,
                    model=model,
                    base_url=base_url,
                    min_chars=min_chars,
                    reasoning_effort=params.reasoning_effort,
                    **brain_kwargs,  # type: ignore[arg-type]
                    session_id=brain_session,
                )
                # IntrospectionEngine shares the SAME resolved provider chain.
                introspection_engine = IntrospectionEngine(
                    get_provider(
                        provider=provider,
                        api_key=api_key,
                        model=model,
                        base_url=base_url,
                        session_id=brain_session,
                    ),
                    reasoning_effort=params.reasoning_effort,
                    **brain_kwargs,  # type: ignore[arg-type]
                    session_id=brain_session,
                )
        self._enricher = enricher
        self.introspection_engine = introspection_engine

    def _provider_api_key(self, provider: str) -> str:
        """Legacy api_key chain for an arbitrary provider.

        settings.<provider>_api_key → RuntimeConfigManager → legacy env var.
        """
        settings_key = getattr(self.settings, f"{provider}_api_key", "")
        if settings_key:
            return str(settings_key)
        try:
            from nous.config.runtime_config import RuntimeConfigManager

            value, _ = RuntimeConfigManager().get_effective_value("api_keys", f"{provider}_api_key")
            if value:
                return str(value)
        except Exception:
            logger.debug("RuntimeConfigManager lookup failed for %s", provider, exc_info=True)
        legacy_env = {
            "anthropic": "ANTHROPIC_API_KEY",
            "openai": "OPENAI_API_KEY",
            "openrouter": "OPENROUTER_API_KEY",
            "google": "GEMINI_API_KEY",
            "opencode_go": "OPENCODE_GO_API_KEY",
        }.get(provider)
        if legacy_env:
            import os

            return os.environ.get(legacy_env, "")
        return ""

    def reload_enricher(self) -> None:
        """Re-resolve the enricher after a config save (chat settings route hook)."""
        self._init_enricher()

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

        # tool.called を chat SSE hub へ転送（内省 curiosity チップのライブ表示, spec C）
        try:
            self.event_bus.subscribe("tool.called", self._on_tool_called_to_hub)
        except Exception as e:
            import logging as _logging

            _logging.getLogger("nous").warning("tool.called→hub bridge init failed: %s", e)

        # tool.called をユーザー由来の対話活動として last_conversation_time に記録（内省は除外）
        try:
            self.event_bus.subscribe("tool.called", self._on_tool_called_record_conversation)
        except Exception as e:
            import logging as _logging

            _logging.getLogger("nous").warning("tool.called→conversation_time bridge init failed: %s", e)

    # ------------------------------------------------------------------
    # ベクトル検証スタック・ライフサイクル・イベント購読は
    # nous/application/context/ 配下の mixin（VectorStackMixin /
    # EventHandlersMixin / LifecycleMixin）が実装本体を担う。
    # AppContext は composition root として継承するのみ（委譲不要）。
    # ------------------------------------------------------------------


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
                raise PersonaValidationError(f"Invalid persona name: '{persona}'")

            persona_root = Path(cls._settings.persona_dir) / persona
            if not persona_root.is_dir():
                raise PersonaNotFoundError(f"Persona '{persona}' not found")

            # config 無し (HTTP 共有依存等が chat より先に ctx を作るケース) →
            # persona の永続 config.json を best-effort で読む。ファイルが無い
            # 場合は None のまま（settings 鎖の契約を維持）。
            if config is None:
                try:
                    import os

                    from nous.config.settings import get_settings
                    from nous.domain.chat_config import ChatConfigFileRepository

                    data_root = str(get_settings().data_root)
                    if os.path.exists(os.path.join(data_root, "persona", persona, "config.json")):
                        config = ChatConfigFileRepository(data_root).get(persona)
                except Exception:
                    logger.debug("persona config load failed for '%s'", persona, exc_info=True)

            ctx = AppContext(cls._settings, persona, config=config)
            cls._contexts[persona] = ctx

            forgetting_enabled = config.forgetting_enabled if config else cls._settings.forgetting.enabled
            if forgetting_enabled:
                from nous.application.chat.reflection import ReflectionEngine
                from nous.application.workers.decay_worker import DecayWorker

                decay_interval = (
                    config.forgetting_decay_interval_seconds
                    if config
                    else cls._settings.forgetting.decay_interval_seconds
                )
                # Periodic reflection (Park et al. 2023): engine + brain LLM provider.
                # brain LLM は enrichment/introspection と同じ解決鎖で解決済み。
                # LLM 無し環境でも AppContext 生成は失敗しない — introspection_engine
                # が無い/持てない場合は getattr が None を返し、DecayWorker 側で no-op
                # フォールバックする（reflection は silent skip）。
                reflection_engine = ReflectionEngine(config=config)
                brain_llm = getattr(getattr(ctx, "introspection_engine", None), "_provider", None)
                decay_worker = DecayWorker(
                    ctx,
                    decay_interval,
                    reflection_engine=reflection_engine,
                    llm_provider=brain_llm,
                    config=config,
                )
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
