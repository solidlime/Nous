"""
Docker-based Sandbox Orchestrator for per-persona OpenSandbox MCP containers.

Manages lifecycle of opensandbox-mcp containers dynamically using the Docker SDK.
Replaces the hardcoded docker-compose services (opensandbox-mcp-herta/alice/bob).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

import docker
from docker.errors import DockerException, NotFound

if TYPE_CHECKING:
    from docker.models.containers import Container

DOCKER_IMAGE = "opensandbox-mcp-nous:latest"
MCP_PORT_INTERNAL = 8000
PORTS_RANGE_START = 8401
PORTS_RANGE_END = 8499
CONTAINER_PREFIX = "opensandbox-mcp-"

logger = logging.getLogger(__name__)


class SandboxOrchestrator:
    """Manages per-persona opensandbox-mcp Docker containers."""

    def __init__(self, network: str = "nous-network", data_dir: str = "/opt/nous/data") -> None:
        self._network = network
        self._data_dir = Path(data_dir)
        self._registry_path = self._data_dir / "sandbox_registry.json"
        self._client: docker.DockerClient | None = None

    @property
    def client(self) -> docker.DockerClient:
        if self._client is None:
            self._client = docker.from_env()
        return self._client

    def _compute_port(self, persona: str) -> int:
        """Hash persona name to a port in [8401, 8499] range."""
        h = hashlib.sha256(persona.encode()).hexdigest()
        offset = int(h, 16) % (PORTS_RANGE_END - PORTS_RANGE_START + 1)
        return PORTS_RANGE_START + offset

    def _container_name(self, persona: str) -> str:
        return f"{CONTAINER_PREFIX}{persona}"

    def _container_labels(self, persona: str) -> dict[str, str]:
        return {"nous.managed": "true", "nous.persona": persona}

    def get_url(self, persona: str) -> str:
        """Get the MCP URL for a persona's sandbox container."""
        name = self._container_name(persona)
        return f"http://{name}:{MCP_PORT_INTERNAL}/mcp"

    def _load_registry(self) -> dict[str, Any]:
        """persona -> {container_id, port, ...} mapping."""
        if self._registry_path.exists():
            try:
                return json.loads(self._registry_path.read_text())
            except Exception:
                return {}
        return {}

    def _save_registry(self, registry: dict[str, Any]) -> None:
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._registry_path.write_text(json.dumps(registry, indent=2))

    def _update_registry(self, persona: str, container_id: str | None) -> None:
        registry = self._load_registry()
        if container_id:
            registry[persona] = {"container_id": container_id, "port": self._compute_port(persona)}
        else:
            registry.pop(persona, None)
        self._save_registry(registry)

    def ensure(self, persona: str) -> bool:
        """Create and start sandbox container for persona if not exists. Idempotent.

        Returns True if container is ready.
        """
        name = self._container_name(persona)
        # Check if already running
        try:
            existing: Container = self.client.containers.get(name)
            if existing.status == "running":
                self._update_registry(persona, existing.id)
                return True
            # Remove dead container
            existing.remove(force=True)
        except NotFound:
            pass

        try:
            container = self.client.containers.run(
                DOCKER_IMAGE,
                name=name,
                detach=True,
                restart_policy={"Name": "unless-stopped"},  # type: ignore[arg-type]
                network=self._network,
                environment={"TZ": "Asia/Tokyo"},
                labels=self._container_labels(persona),
                publish_all_ports=False,
            )
            self._update_registry(persona, container.id)
            logger.info("SandboxOrchestrator: created container %s for persona '%s'", container.short_id, persona)
            return True
        except DockerException as e:
            logger.error("SandboxOrchestrator: failed to create container for '%s': %s", persona, e)
            return False

    def remove(self, persona: str) -> bool:
        """Stop and remove sandbox container for persona. Returns True on success."""
        name = self._container_name(persona)
        try:
            container: Container = self.client.containers.get(name)
            container.stop(timeout=10)
            container.remove(force=True)
            self._update_registry(persona, None)
            logger.info("SandboxOrchestrator: removed container %s for persona '%s'", container.short_id, persona)
            return True
        except NotFound:
            self._update_registry(persona, None)
            return True  # Already gone = success
        except DockerException as e:
            logger.error("SandboxOrchestrator: failed to remove container for '%s': %s", persona, e)
            return False

    def sync_all(self, personas: list[str] | None = None) -> dict[str, str]:
        """Ensure all desired personas have sandbox containers. Remove stale ones.

        If personas is None, auto-detect from NOUS_PERSONAS env var and filesystem.
        """
        if personas is None:
            personas_env = os.environ.get("NOUS_PERSONAS", "")
            if personas_env:
                personas = [p.strip() for p in personas_env.split(",") if p.strip()]
            else:
                # Auto-detect from data directory
                personas = []
                if self._data_dir.exists():
                    for p in self._data_dir.iterdir():
                        if p.is_dir() and (p / "chat.db").exists():
                            personas.append(p.name)

        # Discover existing managed containers
        managed: set[str] = set()
        try:
            containers = self.client.containers.list(
                all=True, filters={"label": "nous.managed=true"}
            )
            managed = {
                c.name.removeprefix(CONTAINER_PREFIX)
                for c in containers
                if c.name
            }
        except DockerException:
            pass

        desired = set(personas or [])
        result: dict[str, str] = {}

        # Create missing
        for p in desired:
            if p not in managed:
                self.ensure(p)
                result[p] = "created"
            else:
                result[p] = "exists"

        # Remove stale (containers whose persona is not in desired set)
        for p in managed - desired:
            if self.remove(p):
                result[p] = "removed"

        return result

    def shutdown(self) -> None:
        """Stop all managed containers."""
        try:
            containers = self.client.containers.list(
                filters={"label": "nous.managed=true"}
            )
            for c in containers:
                try:
                    c.stop(timeout=10)
                    logger.info("SandboxOrchestrator: stopped container %s", c.short_id)
                except DockerException:
                    pass
        except DockerException:
            pass

    # Context manager support for 'with' statement
    def __enter__(self) -> SandboxOrchestrator:
        return self

    def __exit__(self, *args: Any) -> None:
        self.shutdown()


# ── Singleton accessor for cross-module use ──

_orchestrator: SandboxOrchestrator | None = None


def get_orchestrator() -> SandboxOrchestrator | None:
    """Return the global SandboxOrchestrator instance, or None if not initialized."""
    return _orchestrator


def set_orchestrator(orchestrator: SandboxOrchestrator) -> None:
    """Set the global SandboxOrchestrator instance."""
    global _orchestrator
    _orchestrator = orchestrator
