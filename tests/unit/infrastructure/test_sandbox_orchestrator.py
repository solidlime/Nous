"""Unit tests for SandboxOrchestrator. Uses mocks — no real Docker needed."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from docker.errors import NotFound

from nous.infrastructure.sandbox_orchestrator import SandboxOrchestrator

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def orchestrator(tmp_path: Path) -> SandboxOrchestrator:
    return SandboxOrchestrator(network="test-net", data_dir=str(tmp_path))


class TestComputePort:
    def test_deterministic(self, orchestrator: SandboxOrchestrator) -> None:
        p1 = orchestrator._compute_port("herta")
        p2 = orchestrator._compute_port("herta")
        assert p1 == p2

    def test_in_range(self, orchestrator: SandboxOrchestrator) -> None:
        port = orchestrator._compute_port("herta")
        assert 8401 <= port <= 8499


class TestContainerName:
    def test_prefix(self, orchestrator: SandboxOrchestrator) -> None:
        assert orchestrator._container_name("herta") == "opensandbox-mcp-herta"


class TestGetUrl:
    def test_url_format(self, orchestrator: SandboxOrchestrator) -> None:
        url = orchestrator.get_url("herta")
        assert url.startswith("http://opensandbox-mcp-herta:")
        assert url.endswith("/mcp")


class TestRegistry:
    def test_load_empty(self, orchestrator: SandboxOrchestrator) -> None:
        reg = orchestrator._load_registry()
        assert reg == {}

    def test_save_and_load(self, orchestrator: SandboxOrchestrator, tmp_path: Path) -> None:
        orchestrator._save_registry({"herta": {"container_id": "abc123", "port": 8405}})
        reg = orchestrator._load_registry()
        assert reg == {"herta": {"container_id": "abc123", "port": 8405}}

    def test_update_add(self, orchestrator: SandboxOrchestrator) -> None:
        orchestrator._update_registry("herta", "abc123")
        assert orchestrator._load_registry()["herta"]["container_id"] == "abc123"

    def test_update_remove(self, orchestrator: SandboxOrchestrator) -> None:
        orchestrator._update_registry("herta", "abc123")
        orchestrator._update_registry("herta", None)
        assert "herta" not in orchestrator._load_registry()


class TestEnsure:
    def test_creates_container(self, orchestrator: SandboxOrchestrator) -> None:
        mock_client = MagicMock()
        mock_client.containers.get.side_effect = NotFound("not found")
        mock_container = MagicMock()
        mock_container.id = "abc123"
        mock_container.short_id = "abc123"
        mock_client.containers.run.return_value = mock_container
        orchestrator._client = mock_client

        result = orchestrator.ensure("herta")
        assert result is True
        mock_client.containers.run.assert_called_once()

    def test_idempotent(self, orchestrator: SandboxOrchestrator) -> None:
        mock_client = MagicMock()
        mock_container = MagicMock()
        mock_container.id = "abc123"
        mock_container.status = "running"
        mock_client.containers.get.return_value = mock_container
        orchestrator._client = mock_client

        result = orchestrator.ensure("herta")
        assert result is True
        mock_client.containers.run.assert_not_called()


class TestRemove:
    def test_removes_container(self, orchestrator: SandboxOrchestrator) -> None:
        mock_client = MagicMock()
        mock_container = MagicMock()
        mock_container.short_id = "abc123"
        mock_client.containers.get.return_value = mock_container
        orchestrator._client = mock_client

        result = orchestrator.remove("herta")
        assert result is True
        mock_container.stop.assert_called_once()
        mock_container.remove.assert_called_once()

    def test_not_found_is_ok(self, orchestrator: SandboxOrchestrator) -> None:
        mock_client = MagicMock()
        mock_client.containers.get.side_effect = NotFound("not found")
        orchestrator._client = mock_client

        result = orchestrator.remove("herta")
        assert result is True
