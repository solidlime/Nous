"""Unit tests for AppContextRegistry.get() - regression for UnboundLocalError."""

from __future__ import annotations

import threading
from unittest.mock import MagicMock, patch

import pytest

from nous.application.use_cases import AppContextRegistry


@pytest.fixture(autouse=True)
def _reset_registry():
    """各テスト後に Registry の状態をリセットする。"""
    AppContextRegistry._contexts.clear()
    original_settings = AppContextRegistry._settings
    yield
    AppContextRegistry._contexts.clear()
    AppContextRegistry._settings = original_settings


@pytest.fixture()
def persona_root(tmp_path):
    """実在するペルソナディレクトリを用意する（get() は存在確認をするため）。"""
    root = tmp_path / "persona"
    root.mkdir()
    return root


def _mock_settings(persona_root, forgetting_enabled: bool = False):
    s = MagicMock()
    s.persona_dir = str(persona_root)
    s.forgetting.enabled = forgetting_enabled
    s.forgetting.decay_interval_seconds = 3600
    return s


def _ensure_persona(persona_root, name: str):
    d = persona_root / name
    d.mkdir(exist_ok=True)
    return d


class TestAppContextRegistry:
    def test_get_returns_context(self, persona_root):
        """get() が AppContext を返す（UnboundLocalError が起きない）。"""
        settings = _mock_settings(persona_root)
        AppContextRegistry.configure(settings)
        _ensure_persona(persona_root, "test_user")

        with patch("nous.application.use_cases.AppContext") as mock_app_ctx:
            mock_ctx = MagicMock()
            mock_app_ctx.return_value = mock_ctx
            result = AppContextRegistry.get("test_user")
            assert result is mock_ctx

    def test_get_same_persona_twice_no_error(self, persona_root):
        """同一ペルソナで2回 get() しても UnboundLocalError が起きない。（回帰テスト）"""
        settings = _mock_settings(persona_root)
        AppContextRegistry.configure(settings)
        _ensure_persona(persona_root, "alice")

        with patch("nous.application.use_cases.AppContext") as mock_app_ctx:
            mock_ctx = MagicMock()
            mock_app_ctx.return_value = mock_ctx

            ctx1 = AppContextRegistry.get("alice")
            ctx2 = AppContextRegistry.get("alice")  # 2回目 - 以前はここで UnboundLocalError

            assert ctx1 is ctx2
            # AppContext は一度しか作られない
            assert mock_app_ctx.call_count == 1

    def test_get_different_personas_independent(self, persona_root):
        """異なるペルソナは独立したコンテキストを持つ。"""
        settings = _mock_settings(persona_root)
        AppContextRegistry.configure(settings)
        _ensure_persona(persona_root, "alice")
        _ensure_persona(persona_root, "bob")

        with patch("nous.application.use_cases.AppContext") as mock_app_ctx:
            ctx_a = MagicMock()
            ctx_b = MagicMock()
            mock_app_ctx.side_effect = [ctx_a, ctx_b]

            result_a = AppContextRegistry.get("alice")
            result_b = AppContextRegistry.get("bob")

            assert result_a is ctx_a
            assert result_b is ctx_b
            assert result_a is not result_b

    def test_decay_worker_started_only_on_first_get(self, persona_root):
        """DecayWorker はペルソナ初回 get() のみ起動される（毎回起動しない）。"""
        settings = _mock_settings(persona_root, forgetting_enabled=True)
        AppContextRegistry.configure(settings)
        _ensure_persona(persona_root, "alice")

        with (
            patch("nous.application.use_cases.AppContext"),
            patch("nous.application.workers.decay_worker.DecayWorker") as mock_worker_cls,
        ):
            mock_worker = MagicMock()
            mock_worker_cls.return_value = mock_worker

            AppContextRegistry.get("alice")
            AppContextRegistry.get("alice")  # 2回目
            AppContextRegistry.get("alice")  # 3回目

            # 1回しか起動されていない
            assert mock_worker_cls.call_count == 1
            assert mock_worker.start.call_count == 1


class TestAppContextRegistrySecurity:
    """存在しないペルソナでの無検証コンテキスト生成（メモリDoS）対策。"""

    def test_get_nonexistent_persona_raises(self, persona_root):
        """存在しない persona ディレクトリへの get() は ValueError。"""
        AppContextRegistry.configure(_mock_settings(persona_root))

        with patch("nous.application.use_cases.AppContext") as mock_app_ctx:
            with pytest.raises(ValueError, match="not found"):
                AppContextRegistry.get("ghost")
            mock_app_ctx.assert_not_called()

    def test_get_traversal_persona_rejected(self, persona_root):
        """パス分離子・親参照を含む persona はディレクトリが存在しても拒否。"""
        AppContextRegistry.configure(_mock_settings(persona_root))

        for bad in ("..", ".", "a/b", "a\\b"):
            with patch("nous.application.use_cases.AppContext") as mock_app_ctx:
                with pytest.raises(ValueError, match="Invalid persona"):
                    AppContextRegistry.get(bad)
                mock_app_ctx.assert_not_called()

    def test_no_context_cached_for_nonexistent_persona(self, persona_root):
        """失敗した get() でコンテキストがキャッシュされない。"""
        AppContextRegistry.configure(_mock_settings(persona_root))
        with pytest.raises(ValueError):
            AppContextRegistry.get("ghost")
        assert "ghost" not in AppContextRegistry._contexts

    def test_concurrent_get_creates_context_once(self, persona_root):
        """同一 persona への並行 get() でも AppContext は1回だけ生成される。"""
        AppContextRegistry.configure(_mock_settings(persona_root))
        _ensure_persona(persona_root, "concurrent")

        barrier = threading.Barrier(8)
        results: list = []
        errors: list = []

        with patch("nous.application.use_cases.AppContext") as mock_app_ctx:
            mock_ctx = MagicMock()
            mock_app_ctx.return_value = mock_ctx

            def worker():
                try:
                    barrier.wait(timeout=5)
                    results.append(AppContextRegistry.get("concurrent"))
                except Exception as exc:  # noqa: BLE001
                    errors.append(exc)

            threads = [threading.Thread(target=worker) for _ in range(8)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=10)

            assert not errors
            assert len(results) == 8
            assert all(r is mock_ctx for r in results)
            assert mock_app_ctx.call_count == 1
