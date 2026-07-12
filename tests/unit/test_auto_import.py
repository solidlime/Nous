"""Tests for auto-import functionality.

NOTE: zip import tests removed — test data (herta.zip etc.) was never committed
      and is not reproducible in CI environments.
"""

from __future__ import annotations

import contextlib
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from nous.application.auto_import import run_auto_import
from nous.config.settings import Settings


@pytest.fixture
def import_settings(tmp_path):
    """Create Settings with temporary directories for auto-import tests."""
    from nous.application.use_cases import AppContextRegistry

    settings = Settings(data_root=str(tmp_path))
    Path(settings.data_dir).mkdir(parents=True, exist_ok=True)
    Path(settings.import_dir).mkdir(parents=True, exist_ok=True)

    AppContextRegistry.configure(settings)
    return settings


@pytest.fixture(autouse=True)
def _isolate_test(monkeypatch):
    """Isolate each test: mock vector_store property and clean up registry."""
    from nous.application.use_cases import AppContext, AppContextRegistry

    monkeypatch.setattr(AppContext, "vector_store", property(lambda self: None))

    yield

    with contextlib.suppress(Exception):
        AppContextRegistry.close_all()
    AppContextRegistry._contexts.clear()
    AppContextRegistry._settings = None


def test_disabled_when_import_dir_empty(tmp_path):
    """import_dir が空なら即 {} を返し、LegacyImporter は呼ばれない。"""
    mock_importer_cls = MagicMock()

    mock_settings = MagicMock()
    mock_settings.import_dir = ""
    mock_settings.data_dir = str(tmp_path)

    from unittest.mock import patch

    with patch("nous.application.auto_import.LegacyImporter", mock_importer_cls):
        result = run_auto_import(mock_settings)

    assert result == {}
    mock_importer_cls.assert_not_called()


def test_creates_import_dir_if_not_exists(tmp_path):
    """存在しないディレクトリを指定 → 作成されて {} を返す。"""
    non_existent = tmp_path / "does_not_exist"

    mock_settings = MagicMock()
    mock_settings.data_dir = str(tmp_path)
    mock_settings.import_dir = str(non_existent)

    result = run_auto_import(mock_settings)

    assert non_existent.exists()
    assert non_existent.is_dir()
    assert result == {}


def test_empty_directory_returns_empty(import_settings):
    """空のインポートディレクトリ → {} を返す。"""
    result = run_auto_import(import_settings)
    assert result == {}
