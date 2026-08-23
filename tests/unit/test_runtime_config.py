"""Tests for RuntimeConfigManager."""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from nous.config.runtime_config import SETTINGS_META, RuntimeConfigManager
from nous.domain.shared.result import Success

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture(autouse=True)
def _reset_singleton():
    """Reset the singleton before and after each test."""
    RuntimeConfigManager.reset()
    yield
    RuntimeConfigManager.reset()


@pytest.fixture()
def tmp_data_dir(tmp_path: Path):
    """Provide a temporary data directory and patch get_settings to use it."""
    from nous.config.settings import Settings

    mock_settings = Settings(data_root=str(tmp_path))
    with patch("nous.config.runtime_config.get_settings", return_value=mock_settings):
        yield tmp_path


def _wait_for_reload(mgr: RuntimeConfigManager, key: str, timeout: float = 5.0) -> dict:
    """Wait for the background reload thread to finish (status leaves 'loading')."""
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = mgr.reload_status.get(key)
        if status["status"] != "loading":
            return status
        time.sleep(0.01)
    raise AssertionError(f"reload of '{key}' did not complete within {timeout}s")


def test_get_all_returns_all_categories(tmp_data_dir: Path):
    """All categories defined in SETTINGS_META should appear in get_all()."""
    mgr = RuntimeConfigManager()
    result = mgr.get_all()

    assert "settings" in result
    assert "reload_status" in result
    for category in SETTINGS_META:
        assert category in result["settings"], f"Missing category: {category}"
        for key in SETTINGS_META[category]:
            assert key in result["settings"][category], f"Missing key: {category}.{key}"
            entry = result["settings"][category][key]
            assert "value" in entry
            assert "source" in entry


def test_get_effective_value_default(tmp_data_dir: Path):
    """Without env or overrides, the default value from Settings should be returned."""
    mgr = RuntimeConfigManager()

    value, source = mgr.get_effective_value("general", "timezone")
    assert source == "default"
    assert value == "Asia/Tokyo"

    value, source = mgr.get_effective_value("embedding", "model")
    assert source == "default"
    assert value == "onnx-community/ruri-v3-30m-ONNX"


def test_update_hot_reloadable(tmp_data_dir: Path):
    """Updating a hot-reloadable setting should succeed and be reflected."""
    mgr = RuntimeConfigManager()

    result = mgr.update("general", "timezone", "US/Eastern")
    assert result["success"] is True

    value, source = mgr.get_effective_value("general", "timezone")
    assert value == "US/Eastern"
    assert source == "override"


def test_update_non_hot_reloadable(tmp_data_dir: Path):
    """Updating a non-hot-reloadable setting saves to disk with restart_required flag."""
    mgr = RuntimeConfigManager()

    result = mgr.update("server", "port", 9999)
    assert result["success"] is True
    assert result.get("restart_required") is True
    # Verify it was persisted to overrides file
    overrides_file = tmp_data_dir / "config" / "config_overrides.json"
    assert overrides_file.exists()
    import json

    data = json.loads(overrides_file.read_text(encoding="utf-8"))
    assert data.get("server", {}).get("port") == 9999


def test_overrides_persist_to_file(tmp_data_dir: Path):
    """Overrides should be persisted to config_overrides.json."""
    mgr = RuntimeConfigManager()
    mgr.update("general", "log_level", "DEBUG")

    overrides_file = tmp_data_dir / "config" / "config_overrides.json"
    assert overrides_file.exists()

    with open(overrides_file, encoding="utf-8") as f:
        data = json.load(f)
    assert data["general"]["log_level"] == "DEBUG"


def test_callbacks_fire_on_update(tmp_data_dir: Path):
    """Registered callbacks should fire when a setting is updated."""
    mgr = RuntimeConfigManager()
    received: list[tuple[str, object]] = []

    def on_change(key: str, value: object) -> None:
        received.append((key, value))

    mgr.register_callback("general", on_change)
    mgr.update("general", "timezone", "Europe/London")

    assert len(received) == 1
    assert received[0] == ("timezone", "Europe/London")


def test_override_takes_priority_over_env(tmp_data_dir: Path):
    """WebUI overrides should take priority over environment variables."""
    mgr = RuntimeConfigManager()
    mgr.update("general", "timezone", "US/Eastern")

    env_key = "NOUS_TIMEZONE"
    os.environ[env_key] = "UTC"
    try:
        value, source = mgr.get_effective_value("general", "timezone")
        assert source == "override"
        assert value == "US/Eastern"
    finally:
        del os.environ[env_key]


def test_env_used_when_no_override(tmp_data_dir: Path):
    """Environment variable is used as fallback when no override exists."""
    mgr = RuntimeConfigManager()

    env_key = "NOUS_TIMEZONE"
    os.environ[env_key] = "UTC"
    try:
        value, source = mgr.get_effective_value("general", "timezone")
        assert source == "env"
        assert value == "UTC"
    finally:
        del os.environ[env_key]


def test_singleton_pattern(tmp_data_dir: Path):
    """RuntimeConfigManager should return the same instance."""
    mgr1 = RuntimeConfigManager()
    mgr2 = RuntimeConfigManager()
    assert mgr1 is mgr2


# ──────────────────────────────────────────────
# ReloadStatus tests
# ──────────────────────────────────────────────


def test_reload_status_default_for_unknown_key(tmp_data_dir: Path):
    """Getting a status for an unknown key should return default 'ready'."""
    from nous.config.runtime_config import ReloadStatus

    rs = ReloadStatus()
    status = rs.get("nonexistent")
    assert status == {"status": "ready", "progress": None, "error": None}


def test_reload_status_set_and_get(tmp_data_dir: Path):
    """ReloadStatus.set should store values and .get should retrieve them."""
    from nous.config.runtime_config import ReloadStatus

    rs = ReloadStatus()
    rs.set("embedding", "loading", progress=0.5)
    status = rs.get("embedding")
    assert status["status"] == "loading"
    assert status["progress"] == 0.5
    assert status["error"] is None

    # Overwrite
    rs.set("embedding", "ready", error="no error")
    status = rs.get("embedding")
    assert status["status"] == "ready"
    assert status["progress"] is None
    assert status["error"] == "no error"


def test_reload_status_get_all_returns_copy(tmp_data_dir: Path):
    """ReloadStatus.get_all should return all stored statuses."""
    from nous.config.runtime_config import ReloadStatus

    rs = ReloadStatus()
    assert rs.get_all() == {}

    rs.set("embedding", "loading")
    rs.set("reranker", "ready")
    all_s = rs.get_all()
    assert "embedding" in all_s
    assert "reranker" in all_s
    assert len(all_s) == 2
    # Ensure modifying returned dict doesn't affect internal state
    all_s.clear()
    assert "embedding" in rs.get_all()


# ──────────────────────────────────────────────
# Environment variable key formatting
# ──────────────────────────────────────────────


def test_get_env_key_general(tmp_data_dir: Path):
    """General category env vars use NOUS_KEY format."""
    mgr = RuntimeConfigManager()
    assert mgr._get_env_key("general", "timezone") == "NOUS_TIMEZONE"


def test_get_env_key_non_general(tmp_data_dir: Path):
    """Non-general category env vars use NOUS_CATEGORY__KEY format."""
    mgr = RuntimeConfigManager()
    assert mgr._get_env_key("embedding", "model") == "NOUS_EMBEDDING__MODEL"


# ──────────────────────────────────────────────
# Update edge cases
# ──────────────────────────────────────────────


def test_update_unknown_category(tmp_data_dir: Path):
    """Updating an unknown category should return error."""
    mgr = RuntimeConfigManager()
    result = mgr.update("nonexistent", "key", "value")
    assert result["success"] is False
    assert "Unknown setting" in result["error"]


def test_update_unknown_key(tmp_data_dir: Path):
    """Updating an unknown key should return error."""
    mgr = RuntimeConfigManager()
    result = mgr.update("general", "nonexistent_key", "value")
    assert result["success"] is False
    assert "Unknown setting" in result["error"]


# ──────────────────────────────────────────────
# get_effective_value edge cases
# ──────────────────────────────────────────────


def test_get_effective_value_override_source(tmp_data_dir: Path):
    """After update, the source should become 'override'."""
    mgr = RuntimeConfigManager()
    mgr.update("general", "timezone", "Europe/Berlin")
    value, source = mgr.get_effective_value("general", "timezone")
    assert source == "override"
    assert value == "Europe/Berlin"


# ──────────────────────────────────────────────
# get_all details
# ──────────────────────────────────────────────


def test_get_all_masked_values(tmp_data_dir: Path):
    """Masked settings should show '***' when value is truthy."""
    import nous.config.runtime_config as rc

    mgr = RuntimeConfigManager()
    result = mgr.get_all()
    for category, keys in rc.SETTINGS_META.items():
        for key, meta in keys.items():
            if meta.get("masked"):
                entry = result["settings"][category][key]
                assert entry["value"] == "***" or entry.get("value") is None or entry.get("value") == ""


def test_get_all_includes_reload_status(tmp_data_dir: Path):
    """get_all() should include reload_status section."""
    mgr = RuntimeConfigManager()
    result = mgr.get_all()
    assert "reload_status" in result
    assert isinstance(result["reload_status"], dict)


# ──────────────────────────────────────────────
# Callback edge cases
# ──────────────────────────────────────────────


def test_callback_exception_does_not_block_others(tmp_data_dir: Path):
    """When a callback raises, other callbacks should still fire."""
    mgr = RuntimeConfigManager()
    received: list[tuple[str, object]] = []

    def failing_cb(key: str, value: object) -> None:
        raise ValueError("oops")

    def working_cb(key: str, value: object) -> None:
        received.append((key, value))

    mgr.register_callback("general", failing_cb)
    mgr.register_callback("general", working_cb)
    mgr.update("general", "timezone", "Asia/Shanghai")

    assert len(received) == 1
    assert received[0] == ("timezone", "Asia/Shanghai")


def test_register_callback_new_category(tmp_data_dir: Path):
    """register_callback should create a new list for an unused category."""
    mgr = RuntimeConfigManager()
    received: list[tuple[str, object]] = []

    def cb(key: str, value: object) -> None:
        received.append((key, value))

    mgr.register_callback("embedding", cb)
    mgr.update("embedding", "model", "new-model")

    assert len(received) == 1
    assert received[0] == ("model", "new-model")


# ──────────────────────────────────────────────
# _load_overrides edge cases
# ──────────────────────────────────────────────


def test_load_overrides_invalid_json(tmp_path: Path):
    """Invalid JSON in config_overrides.json should be handled gracefully."""
    from nous.config.settings import Settings

    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True)
    overrides_file = config_dir / "config_overrides.json"
    overrides_file.write_text("{invalid json}")

    mock_settings = Settings(data_root=str(tmp_path))
    with patch("nous.config.runtime_config.get_settings", return_value=mock_settings):
        mgr = RuntimeConfigManager()
        assert mgr._overrides == {}


# ──────────────────────────────────────────────
# _get_settings_value / _get_default_value edge cases
# ──────────────────────────────────────────────


def test_get_settings_value_nonexistent_category(tmp_data_dir: Path):
    """Getting a value for a nonexistent category should return None."""
    mgr = RuntimeConfigManager()
    assert mgr._get_settings_value("nonexistent", "key") is None


def test_get_default_value_nonexistent(tmp_data_dir: Path):
    """Getting a default for a nonexistent category should return None."""
    mgr = RuntimeConfigManager()
    assert mgr._get_default_value("nonexistent", "key") is None


# ──────────────────────────────────────────────
# _apply_setting for general and sub-category
# ──────────────────────────────────────────────


def test_apply_setting_general(tmp_data_dir: Path):
    """_apply_setting should update top-level Settings attributes."""
    mgr = RuntimeConfigManager()
    mgr._apply_setting("general", "timezone", "US/Pacific")
    assert mgr._settings.timezone == "US/Pacific"


def test_apply_setting_sub_category(tmp_data_dir: Path):
    """_apply_setting should update sub-category Settings attributes."""
    mgr = RuntimeConfigManager()
    mgr._apply_setting("embedding", "model", "test-model")
    assert mgr._settings.embedding.model == "test-model"


# ──────────────────────────────────────────────
# register_model_reload_callbacks
# ──────────────────────────────────────────────


def test_register_model_reload_callbacks(tmp_data_dir: Path):
    """register_model_reload_callbacks should register 3 callbacks."""
    from nous.config.runtime_config import register_model_reload_callbacks

    mgr = RuntimeConfigManager()
    register_model_reload_callbacks(mgr)

    assert "embedding" in mgr._callbacks
    assert "reranker" in mgr._callbacks
    assert "qdrant" in mgr._callbacks
    assert all(len(cbs) == 1 for cbs in mgr._callbacks.values())


def test_embedding_reload_callback_fires(tmp_data_dir: Path):
    """The embedding reload callback should fire on embedding setting update."""
    from unittest.mock import MagicMock

    from nous.application.use_cases import AppContextRegistry
    from nous.config.runtime_config import register_model_reload_callbacks

    mgr = RuntimeConfigManager()
    register_model_reload_callbacks(mgr)

    # Create a mock context with _embedding
    mock_ctx = MagicMock()
    mock_ctx._embedding = MagicMock()
    mock_ctx._embedding.reload_model.return_value = {"status": "ready", "message": "ok"}
    mock_ctx._search_engine = MagicMock()

    AppContextRegistry._contexts["test_persona"] = mock_ctx

    try:
        result = mgr.update("embedding", "model", "new-model")
        assert result["success"] is True
        _wait_for_reload(mgr, "embedding")
        mock_ctx._embedding.reload_model.assert_called_once_with(new_model_name="new-model")
        assert mock_ctx._search_engine is None
    finally:
        AppContextRegistry._contexts.clear()


def test_embedding_reload_callback_device(tmp_data_dir: Path):
    """The embedding reload callback with device key should pass new_device."""
    from unittest.mock import MagicMock

    from nous.application.use_cases import AppContextRegistry
    from nous.config.runtime_config import register_model_reload_callbacks

    mgr = RuntimeConfigManager()
    register_model_reload_callbacks(mgr)

    mock_ctx = MagicMock()
    mock_ctx._embedding = MagicMock()
    mock_ctx._embedding.reload_model.return_value = {"status": "ready", "message": "ok"}
    mock_ctx._search_engine = MagicMock()

    AppContextRegistry._contexts["test_persona"] = mock_ctx

    try:
        result = mgr.update("embedding", "device", "cuda")
        assert result["success"] is True
        _wait_for_reload(mgr, "embedding")
        mock_ctx._embedding.reload_model.assert_called_once_with(new_device="cuda")
    finally:
        AppContextRegistry._contexts.clear()


def test_embedding_reload_with_error_status(tmp_data_dir: Path):
    """When embedding reload returns error, status should reflect it."""
    from unittest.mock import MagicMock

    from nous.application.use_cases import AppContextRegistry
    from nous.config.runtime_config import register_model_reload_callbacks

    mgr = RuntimeConfigManager()
    register_model_reload_callbacks(mgr)

    mock_ctx = MagicMock()
    mock_ctx._embedding = MagicMock()
    mock_ctx._embedding.reload_model.return_value = {"status": "error", "message": "OOM"}
    mock_ctx._search_engine = MagicMock()

    AppContextRegistry._contexts["test_persona"] = mock_ctx

    try:
        mgr.update("embedding", "model", "bad-model")
        status = _wait_for_reload(mgr, "embedding")
        assert status["status"] == "error"
    finally:
        AppContextRegistry._contexts.clear()


def test_reranker_reload_callback(tmp_data_dir: Path):
    """The reranker reload callback should fire on reranker setting update."""
    from unittest.mock import MagicMock

    from nous.application.use_cases import AppContextRegistry
    from nous.config.runtime_config import register_model_reload_callbacks

    mgr = RuntimeConfigManager()
    register_model_reload_callbacks(mgr)

    mock_ctx = MagicMock()
    mock_ctx._reranker = MagicMock()
    mock_ctx._reranker.reload_model.return_value = {"status": "ready", "message": "ok"}

    AppContextRegistry._contexts["test"] = mock_ctx

    try:
        result = mgr.update("reranker", "model", "new-reranker")
        assert result["success"] is True
        _wait_for_reload(mgr, "reranker")
        mock_ctx._reranker.reload_model.assert_called_once_with(new_model_name="new-reranker")
    finally:
        AppContextRegistry._contexts.clear()


def test_reranker_enabled_callback(tmp_data_dir: Path):
    """Reranker enabled change should pass new_enabled."""
    from unittest.mock import MagicMock

    from nous.application.use_cases import AppContextRegistry
    from nous.config.runtime_config import register_model_reload_callbacks

    mgr = RuntimeConfigManager()
    register_model_reload_callbacks(mgr)

    mock_ctx = MagicMock()
    mock_ctx._reranker = MagicMock()
    mock_ctx._reranker.reload_model.return_value = {"status": "disabled", "message": "disabled"}

    AppContextRegistry._contexts["test"] = mock_ctx

    try:
        result = mgr.update("reranker", "enabled", False)
        assert result["success"] is True
        _wait_for_reload(mgr, "reranker")
        mock_ctx._reranker.reload_model.assert_called_once_with(new_enabled=False)
    finally:
        AppContextRegistry._contexts.clear()


def test_qdrant_reload_callback_url(tmp_data_dir: Path):
    """Qdrant URL change should trigger reconnect."""
    from unittest.mock import AsyncMock, MagicMock

    from nous.application.use_cases import AppContextRegistry
    from nous.config.runtime_config import register_model_reload_callbacks

    mgr = RuntimeConfigManager()
    register_model_reload_callbacks(mgr)

    mock_ctx = MagicMock()
    mock_ctx._vector_store = MagicMock()
    mock_ctx._vector_store.reconnect = AsyncMock(return_value={"status": "connected", "message": "ok"})
    mock_ctx._search_engine = MagicMock()

    AppContextRegistry._contexts["test"] = mock_ctx

    try:
        result = mgr.update("qdrant", "url", "http://new-url:6333")
        assert result["success"] is True
        mock_ctx._vector_store.reconnect.assert_called_once_with(new_url="http://new-url:6333")
        assert mock_ctx._search_engine is None
    finally:
        AppContextRegistry._contexts.clear()


def test_qdrant_reload_callback_api_key(tmp_data_dir: Path):
    """Qdrant API key change should trigger reconnect."""
    from unittest.mock import AsyncMock, MagicMock

    from nous.application.use_cases import AppContextRegistry
    from nous.config.runtime_config import register_model_reload_callbacks

    mgr = RuntimeConfigManager()
    register_model_reload_callbacks(mgr)

    mock_ctx = MagicMock()
    mock_ctx._vector_store = MagicMock()
    mock_ctx._vector_store.reconnect = AsyncMock(return_value={"status": "connected", "message": "ok"})

    AppContextRegistry._contexts["test"] = mock_ctx

    try:
        result = mgr.update("qdrant", "api_key", "new-key")
        assert result["success"] is True
        mock_ctx._vector_store.reconnect.assert_called_once_with(new_api_key="new-key")
    finally:
        AppContextRegistry._contexts.clear()


def test_qdrant_collection_prefix_change(tmp_data_dir: Path):
    """Qdrant collection_prefix change should trigger reconnect and ensure_collection."""
    from unittest.mock import AsyncMock, MagicMock

    from nous.application.use_cases import AppContextRegistry
    from nous.config.runtime_config import register_model_reload_callbacks

    mgr = RuntimeConfigManager()
    register_model_reload_callbacks(mgr)

    mock_ctx = MagicMock()
    mock_ctx._vector_store = MagicMock()
    mock_ctx._vector_store.reconnect = AsyncMock(return_value={"status": "connected", "message": "ok"})
    mock_ctx._vector_store.ensure_collection = AsyncMock(return_value=Success(None))
    mock_ctx._search_engine = MagicMock()

    AppContextRegistry._contexts["test_persona"] = mock_ctx

    try:
        result = mgr.update("qdrant", "collection_prefix", "new_prefix")
        assert result["success"] is True
        mock_ctx._vector_store.reconnect.assert_called_once()
        assert mock_ctx._vector_store.collection_prefix == "new_prefix"
        mock_ctx._vector_store.ensure_collection.assert_called_once_with("test_persona")
        assert mock_ctx._search_engine is None
    finally:
        AppContextRegistry._contexts.clear()
