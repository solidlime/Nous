"""Phase 3c tests: ContextSnapshotWorker memorag flag gating.

- settings.memorag.enabled=False (global infra kill switch) → thread never starts
- _rebuild_persona skips personas whose ChatConfig.memorag_enabled is False
  (config source = ChatConfigFileRepository / config.json — same as the chat path)
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from nous.application.workers.context_snapshot_worker import ContextSnapshotWorker


def _make_settings(enabled: bool = True) -> MagicMock:
    settings = MagicMock()
    settings.memorag.enabled = enabled
    settings.memorag.snapshot_interval_hours = 24
    settings.memorag.rebuild_threshold = 20
    settings.memorag.snapshot_top_memories = 20
    return settings


def _write_persona_config(tmp_path, memorag_enabled: bool, memorag_top_k: int | None = None) -> None:
    persona_dir = tmp_path / "persona" / "test_persona"
    persona_dir.mkdir(parents=True, exist_ok=True)
    data: dict = {"persona": "test_persona", "memorag_enabled": memorag_enabled}
    if memorag_top_k is not None:
        data["memorag_top_k"] = memorag_top_k
    (persona_dir / "config.json").write_text(json.dumps(data), encoding="utf-8")


class TestGlobalKillSwitch:
    def test_disabled_settings_never_starts_thread(self):
        worker = ContextSnapshotWorker(_make_settings(enabled=False))
        worker.start()
        assert worker._thread is None

    def test_enabled_settings_starts_thread(self):
        worker = ContextSnapshotWorker(_make_settings(enabled=True))
        worker.start()
        try:
            assert worker._thread is not None
            assert worker._thread.is_alive()
        finally:
            worker.stop(timeout=5)


class TestPerPersonaGating:
    def _make_ctx(self) -> MagicMock:
        return MagicMock()

    def test_rebuild_persona_skips_when_memorag_disabled(self, tmp_path):
        """config.json の memorag_enabled=False ペルソナは snapshot を再構築しない."""
        _write_persona_config(tmp_path, memorag_enabled=False)
        ctx = self._make_ctx()

        worker = ContextSnapshotWorker(_make_settings(enabled=True))
        with (
            patch("nous.config.settings.get_settings", return_value=MagicMock(data_root=str(tmp_path))),
            patch("nous.application.use_cases.AppContextRegistry.get", return_value=ctx),
            patch("nous.domain.search.context_snapshot.MemoryContextSnapshot") as mock_snap,
        ):
            worker._rebuild_persona("test_persona", threshold=20)

        mock_snap.build.assert_not_called()
        mock_snap.load.assert_not_called()

    def test_rebuild_persona_runs_when_memorag_enabled(self, tmp_path):
        """config.json の memorag_enabled=True ペルソナは snapshot を再構築する."""
        _write_persona_config(tmp_path, memorag_enabled=True)
        ctx = self._make_ctx()
        ctx.memory_repo.count.return_value = MagicMock(is_ok=True, value=5)

        worker = ContextSnapshotWorker(_make_settings(enabled=True))
        with (
            patch("nous.config.settings.get_settings", return_value=MagicMock(data_root=str(tmp_path))),
            patch("nous.application.use_cases.AppContextRegistry.get", return_value=ctx),
            patch("nous.domain.search.context_snapshot.MemoryContextSnapshot") as mock_snap,
        ):
            mock_snap.load.return_value = None
            worker._rebuild_persona("test_persona", threshold=20)

        mock_snap.build.assert_called_once()
        mock_snap.build.return_value.save.assert_called_once()

    def test_persona_top_k_preferred_over_settings(self, tmp_path):
        """memorag_top_k はペルソナ設定（config.json）が settings より優先される."""
        _write_persona_config(tmp_path, memorag_enabled=True, memorag_top_k=7)
        ctx = self._make_ctx()
        ctx.memory_repo.count.return_value = MagicMock(is_ok=True, value=5)

        worker = ContextSnapshotWorker(_make_settings(enabled=True))
        with (
            patch("nous.config.settings.get_settings", return_value=MagicMock(data_root=str(tmp_path))),
            patch("nous.application.use_cases.AppContextRegistry.get", return_value=ctx),
            patch("nous.domain.search.context_snapshot.MemoryContextSnapshot") as mock_snap,
        ):
            mock_snap.load.return_value = None
            worker._rebuild_persona("test_persona", threshold=20)

        assert mock_snap.build.call_args.kwargs["top_n"] == 7
