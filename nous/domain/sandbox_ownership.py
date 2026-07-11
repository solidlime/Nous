"""Sandbox ID ownership registry for persona-isolated sandbox_list filtering.

OpenSandbox backend has no persona concept, so all MCP instances see all sandboxes.
This module tracks which sandbox_id belongs to which persona via a JSON registry file,
and filters sandbox_list results accordingly.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_REGISTRY_FILENAME = "_sandbox_owners.json"


class SandboxOwnershipRegistry:
    """Manages sandbox_id → persona ownership mapping, persisted to JSON."""

    def __init__(self, data_dir: str) -> None:
        self._path = Path(data_dir) / _REGISTRY_FILENAME

    def _load(self) -> dict[str, str]:
        """Returns {sandbox_id: persona} mapping."""
        if self._path.exists():
            try:
                return json.loads(self._path.read_text())
            except Exception:
                logger.warning("SandboxOwnershipRegistry: failed to load, starting fresh")
                return {}
        return {}

    def _save(self, data: dict[str, str]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(data, indent=2))

    def record(self, persona: str, sandbox_id: str) -> None:
        """Record that a sandbox belongs to a persona."""
        if not persona or not sandbox_id:
            return
        data = self._load()
        data[sandbox_id] = persona
        self._save(data)
        logger.debug("SandboxOwnershipRegistry: %s owns %s", persona, sandbox_id)

    def remove(self, sandbox_id: str) -> None:
        """Remove sandbox ownership record."""
        data = self._load()
        if sandbox_id in data:
            del data[sandbox_id]
            self._save(data)
            logger.debug("SandboxOwnershipRegistry: removed %s", sandbox_id)

    def list_owned(self, persona: str) -> set[str]:
        """Get all sandbox_ids owned by a persona."""
        data = self._load()
        return {sid for sid, owner in data.items() if owner == persona}

    def cleanup_persona(self, persona: str) -> int:
        """Remove all sandbox ownership records for a persona. Returns count removed."""
        data = self._load()
        to_remove = [sid for sid, owner in data.items() if owner == persona]
        for sid in to_remove:
            del data[sid]
        if to_remove:
            self._save(data)
            logger.info("SandboxOwnershipRegistry: cleaned up %d sandboxes for %s", len(to_remove), persona)
        return len(to_remove)


# ── Singleton convenience ──

_registry: SandboxOwnershipRegistry | None = None


def get_registry(data_dir: str) -> SandboxOwnershipRegistry:
    """Get or create the singleton SandboxOwnershipRegistry for the given data_dir."""
    global _registry
    if _registry is None or str(_registry._path.parent) != str(Path(data_dir)):
        _registry = SandboxOwnershipRegistry(data_dir)
    return _registry
