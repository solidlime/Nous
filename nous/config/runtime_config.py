"""Runtime configuration manager with hot-reload support."""

from __future__ import annotations

import asyncio
import json
import os
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

from nous.config.settings import Settings, get_settings
from nous.infrastructure.logging.structured import get_logger

logger = get_logger(__name__)


# Settings metadata: which settings can be hot-reloaded
SETTINGS_META: dict[str, dict[str, dict]] = {
    "api_keys": {
        "anthropic_api_key": {"hot_reload": True, "description": "Anthropic API key", "masked": True},
        "openai_api_key": {"hot_reload": True, "description": "OpenAI API key", "masked": True},
        "openrouter_api_key": {"hot_reload": True, "description": "OpenRouter API key", "masked": True},
    },
    "server": {
        "host": {"hot_reload": False, "description": "Server bind address"},
        "port": {"hot_reload": False, "description": "Server port"},
    },
    "embedding": {
        "model": {"hot_reload": True, "description": "Embedding model name", "reload_time": "10-60s"},
        "device": {"hot_reload": True, "description": "Device (cpu/cuda)", "reload_time": "10-60s"},
        "batch_size": {"hot_reload": True, "description": "Embedding batch size"},
    },
    "reranker": {
        "model": {"hot_reload": True, "description": "Reranker model name", "reload_time": "5-30s"},
        "enabled": {"hot_reload": True, "description": "Enable reranker"},
    },
    "qdrant": {
        "url": {"hot_reload": True, "description": "Qdrant server URL", "reload_time": "1-3s"},
        "api_key": {"hot_reload": True, "description": "Qdrant API key", "masked": True},
        "collection_prefix": {"hot_reload": True, "description": "Collection name prefix"},
    },
    "forgetting": {
        "enabled": {"hot_reload": True, "description": "Enable forgetting curve"},
        "decay_interval_seconds": {"hot_reload": True, "description": "Decay worker interval (seconds)"},
        "min_strength": {"hot_reload": True, "description": "Minimum memory strength"},
        "emotion_half_life_hours": {"hot_reload": True, "description": "Base half-life for emotion decay (hours)"},
    },
    "memory_enrichment": {
        "enabled": {"hot_reload": True, "description": "Auto-evaluate importance & relations via LLM"},
        "provider": {"hot_reload": True, "description": "LLM provider (anthropic/openai/openrouter)"},
        "api_key": {"hot_reload": True, "description": "LLM API key", "masked": True},
        "model": {"hot_reload": True, "description": "LLM model for enrichment"},
        "base_url": {"hot_reload": True, "description": "LLM API base URL"},
        "min_chars": {"hot_reload": True, "description": "Min content length to trigger enrichment"},
    },
    "irodori": {
        "enabled": {"hot_reload": True, "description": "Enable Irodori-TTS voice generation"},
        "url": {"hot_reload": True, "description": "Irodori-TTS server URL (OpenAI-compatible endpoint)"},
        "voice": {"hot_reload": True, "description": "Default voice name"},
        "timeout_seconds": {"hot_reload": True, "description": "Generation timeout (seconds)"},
    },
    "auto_capture": {
        "enabled": {"hot_reload": True, "description": "Auto-capture memories at end of each chat turn"},
        "max_memories": {"hot_reload": True, "description": "Maximum memories to create per session"},
    },
    "memorag": {
        "enabled": {"hot_reload": True, "description": "Enable MemoryContextSnapshot building"},
        "clue_generation_enabled": {"hot_reload": True, "description": "Enable LLM-based clue generation for memorag search mode"},
        "rebuild_threshold": {"hot_reload": True, "description": "Rebuild snapshot when memory count increases by this many"},
        "snapshot_top_memories": {"hot_reload": True, "description": "Number of top-importance memories in snapshot"},
        "snapshot_interval_hours": {"hot_reload": True, "description": "Minimum hours between automatic snapshot rebuilds"},
    },
    "portrait_gen": {
        "provider": {"hot_reload": True, "description": "Generation backend (comfyui/openai/stability)"},
        "comfyui_url": {"hot_reload": True, "description": "ComfyUI API address"},
        "auto_generate": {"hot_reload": True, "description": "Auto-generate portrait on emotion change"},
        "generate_interval_min": {"hot_reload": True, "description": "Minimum minutes between auto-generations"},
        "size": {"hot_reload": True, "description": "Preview size"},
        "quality": {"hot_reload": True, "description": "Generation quality"},
        "emotion_threshold": {"hot_reload": True, "description": "Emotion intensity change threshold for regeneration"},
        "max_monthly_budget": {"hot_reload": True, "description": "Monthly USD cap for cloud providers"},
        "healthcheck_enabled": {"hot_reload": True, "description": "Periodically check if ComfyUI is reachable"},
        "healthcheck_interval_seconds": {"hot_reload": True, "description": "Interval between health checks"},
    },
    "plugin": {
        "enabled": {"hot_reload": True, "description": "Enable plugin API access"},
        "api_key": {"hot_reload": True, "description": "Plugin API key", "masked": True},
    },
    "general": {
        "timezone": {"hot_reload": True, "description": "Timezone"},
        "log_level": {"hot_reload": True, "description": "Log level"},
        "data_dir": {"hot_reload": False, "description": "Data directory"},
        "import_dir": {"hot_reload": True, "description": "Auto-import directory"},
        "default_persona": {"hot_reload": True, "description": "Default persona"},
        "contradiction_threshold": {"hot_reload": True, "description": "Contradiction detection threshold"},
        "duplicate_threshold": {"hot_reload": True, "description": "Duplicate detection threshold"},
    },
}


class ReloadStatus:
    """Track status of model/service reloads."""

    def __init__(self) -> None:
        self._statuses: dict[str, dict] = {}
        self._lock = threading.Lock()

    def set(self, key: str, status: str, progress: float | None = None, error: str | None = None) -> None:
        with self._lock:
            self._statuses[key] = {"status": status, "progress": progress, "error": error}

    def get(self, key: str) -> dict:
        with self._lock:
            return self._statuses.get(key, {"status": "ready", "progress": None, "error": None})

    def get_all(self) -> dict:
        with self._lock:
            return dict(self._statuses)


class RuntimeConfigManager:
    """Singleton manager for runtime configuration with hot-reload."""

    _instance: RuntimeConfigManager | None = None
    _lock = threading.Lock()

    def __new__(cls) -> RuntimeConfigManager:
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        self._settings = get_settings()
        self._default_settings = Settings()
        self._overrides: dict[str, Any] = {}
        self._callbacks: dict[str, list[Callable]] = {}
        self._reload_status = ReloadStatus()
        self._overrides_path = Path(self._settings.config_dir) / "config_overrides.json"
        self._load_overrides()

    def _load_overrides(self) -> None:
        """Load overrides from JSON file."""
        if self._overrides_path.exists():
            try:
                with open(self._overrides_path) as f:
                    self._overrides = json.load(f)
                logger.info("Loaded config overrides from %s", self._overrides_path)
            except Exception:
                logger.exception("Failed to load config overrides")
                self._overrides = {}

    def _save_overrides(self) -> None:
        """Persist overrides to JSON file."""
        self._overrides_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._overrides_path, "w") as f:
            json.dump(self._overrides, f, indent=2, ensure_ascii=False)
        logger.info("Saved config overrides to %s", self._overrides_path)

    def get_effective_value(self, category: str, key: str) -> tuple[Any, str]:
        """Get the effective value and its source for a setting.

        Returns: (value, source) where source is "override", "env", or "default"
        """
        # Check overrides first (WebUI takes priority over environment variables)
        override_val = self._overrides.get(category, {}).get(key)
        if override_val is not None:
            return (override_val, "override")

        # Check environment variable
        env_key = self._get_env_key(category, key)
        env_val = os.environ.get(env_key)
        if env_val is not None:
            return (env_val, "env")

        # Fall back to default from Settings
        return (self._get_settings_value(category, key), "default")

    def _get_env_key(self, category: str, key: str) -> str:
        """Construct environment variable name."""
        if category in ("general", "api_keys"):
            return f"NOUS_{key.upper()}"
        return f"NOUS_{category.upper()}__{key.upper()}"

    def _get_settings_value(self, category: str, key: str) -> Any:
        """Get value from current Settings instance."""
        if category == "general":
            return getattr(self._settings, key, None)
        sub = getattr(self._settings, category, None)
        if sub is not None:
            return getattr(sub, key, None)
        return None

    def _get_default_value(self, category: str, key: str) -> Any:
        """Get the default value for a setting from a clean Settings instance."""
        if category == "general":
            return getattr(self._default_settings, key, None)
        sub = getattr(self._default_settings, category, None)
        if sub is not None:
            return getattr(sub, key, None)
        return None

    def get_all(self) -> dict:
        """Get all settings with metadata for the dashboard."""
        result: dict[str, dict] = {}
        for category, keys in SETTINGS_META.items():
            result[category] = {}
            for key, meta in keys.items():
                value, source = self.get_effective_value(category, key)
                default_val = self._get_default_value(category, key)
                entry = {
                    "value": "***" if meta.get("masked") and value else value,
                    "default_value": default_val,
                    "source": source,
                    **meta,
                }
                result[category][key] = entry
        return {
            "settings": result,
            "reload_status": self._reload_status.get_all(),
        }

    def update(self, category: str, key: str, value: Any) -> dict:
        """Update a setting. Returns status dict."""
        # Validate category/key
        if category not in SETTINGS_META or key not in SETTINGS_META[category]:
            return {"success": False, "error": f"Unknown setting: {category}.{key}"}

        meta = SETTINGS_META[category][key]
        if not meta.get("hot_reload", False):
            # Save override to disk even if restart is needed
            if category not in self._overrides:
                self._overrides[category] = {}
            self._overrides[category][key] = value
            self._save_overrides()
            return {
                "success": True,
                "restart_required": True,
                "message": f"{category}.{key} saved. Server restart required to apply changes.",
            }

        # Save override
        if category not in self._overrides:
            self._overrides[category] = {}
        self._overrides[category][key] = value
        self._save_overrides()

        # Apply to in-memory settings
        self._apply_setting(category, key, value)

        # Fire callbacks
        self._fire_callbacks(category, key, value)

        logger.info("Updated setting %s.%s = %s", category, key, value)
        return {"success": True, "category": category, "key": key, "value": value}

    def _apply_setting(self, category: str, key: str, value: Any) -> None:
        """Apply setting change to the in-memory Settings object."""
        if category == "general":
            setattr(self._settings, key, value)
        else:
            sub = getattr(self._settings, category, None)
            if sub is not None:
                setattr(sub, key, value)

    def register_callback(self, category: str, callback: Callable[[str, Any], None]) -> None:
        """Register a callback for when a setting in the given category changes.

        Callback receives (key, new_value).
        """
        if category not in self._callbacks:
            self._callbacks[category] = []
        self._callbacks[category].append(callback)

    def _fire_callbacks(self, category: str, key: str, value: Any) -> None:
        """Fire registered callbacks for the category."""
        for cb in self._callbacks.get(category, []):
            try:
                cb(key, value)
            except Exception:
                logger.exception("Callback failed for %s.%s", category, key)

    @property
    def reload_status(self) -> ReloadStatus:
        return self._reload_status

    @classmethod
    def reset(cls) -> None:
        """Reset singleton (for testing)."""
        with cls._lock:
            cls._instance = None


def register_model_reload_callbacks(config_manager: RuntimeConfigManager) -> None:
    """embedding/reranker/qdrantのホットリロードコールバックを登録する。

    AppContextRegistryの全ペルソナのコンテキストに対してモデルリロードを実行する。
    """
    from nous.application.use_cases import AppContextRegistry

    def on_embedding_change(key: str, new_value: Any) -> None:
        """Embeddingモデル設定変更時のコールバック。"""
        config_manager.reload_status.set("embedding", "loading")
        logger.info("Embedding config changed: %s = %s", key, new_value)

        results = []
        for persona, ctx in AppContextRegistry._contexts.items():
            if ctx._embedding is not None:
                kwargs = {}
                if key == "model":
                    kwargs["new_model_name"] = new_value
                elif key == "device":
                    kwargs["new_device"] = new_value
                result = ctx._embedding.reload_model(**kwargs)
                results.append({"persona": persona, **result})
                # search_engine をリセット（embedding変更で再構築が必要）
                ctx._search_engine = None

        status = "ready" if all(r.get("status") == "ready" for r in results) else "error"
        error_msg = "; ".join(r["message"] for r in results if r.get("status") == "error") or None
        config_manager.reload_status.set("embedding", status, error=error_msg)
        logger.info("Embedding reload complete: %s (%d contexts)", status, len(results))

    def on_reranker_change(key: str, new_value: Any) -> None:
        """Rerankerモデル設定変更時のコールバック。"""
        config_manager.reload_status.set("reranker", "loading")
        logger.info("Reranker config changed: %s = %s", key, new_value)

        results = []
        for persona, ctx in AppContextRegistry._contexts.items():
            if ctx._reranker is not None:
                kwargs = {}
                if key == "model":
                    kwargs["new_model_name"] = new_value
                elif key == "enabled":
                    kwargs["new_enabled"] = new_value
                result = ctx._reranker.reload_model(**kwargs)
                results.append({"persona": persona, **result})
                # search_engine をリセット（reranker変更で再構築が必要）
                ctx._search_engine = None

        status = "ready" if all(r.get("status") in ("ready", "disabled") for r in results) else "error"
        error_msg = "; ".join(r["message"] for r in results if r.get("status") == "error") or None
        config_manager.reload_status.set("reranker", status, error=error_msg)
        logger.info("Reranker reload complete: %s (%d contexts)", status, len(results))

    def on_qdrant_change(key: str, new_value: Any) -> None:
        """Qdrant設定変更時のコールバック。"""
        asyncio.run(_on_qdrant_change_async(key, new_value))

    async def _on_qdrant_change_async(key: str, new_value: Any) -> None:
        """Async implementation of Qdrant change handler."""
        config_manager.reload_status.set("qdrant", "loading")
        logger.info("Qdrant config changed: %s = %s", key, new_value if key != "api_key" else "***")

        results = []
        for persona, ctx in AppContextRegistry._contexts.items():
            if ctx._vector_store is not None:
                kwargs = {}
                if key == "url":
                    kwargs["new_url"] = new_value
                elif key == "api_key":
                    kwargs["new_api_key"] = new_value
                result = await ctx._vector_store.reconnect(**kwargs)
                results.append({"persona": persona, **result})
                # collection_prefix 変更時はvector_storeをリセット
                if key == "collection_prefix":
                    ctx._vector_store.collection_prefix = new_value
                    await ctx._vector_store.ensure_collection(persona)
                # search_engine をリセット
                ctx._search_engine = None

        status = "ready" if all(r.get("status") == "connected" for r in results) else "error"
        error_msg = "; ".join(r["message"] for r in results if r.get("status") == "error") or None
        config_manager.reload_status.set("qdrant", status, error=error_msg)
        logger.info("Qdrant reload complete: %s (%d contexts)", status, len(results))

    config_manager.register_callback("embedding", on_embedding_change)
    config_manager.register_callback("reranker", on_reranker_change)
    config_manager.register_callback("qdrant", on_qdrant_change)
    logger.info("Model reload callbacks registered")
