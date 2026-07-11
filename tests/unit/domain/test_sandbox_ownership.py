"""Unit tests for SandboxOwnershipRegistry."""
from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from nous.domain.sandbox_ownership import (
    _REGISTRY_FILENAME,
    SandboxOwnershipRegistry,
    get_registry,
)

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def registry(tmp_path: Path) -> SandboxOwnershipRegistry:
    return SandboxOwnershipRegistry(str(tmp_path))


class TestRecordAndList:
    def test_record_and_list(self, registry: SandboxOwnershipRegistry) -> None:
        registry.record("herta", "sbx-001")
        assert registry.list_owned("herta") == {"sbx-001"}

    def test_multiple_sandboxes(self, registry: SandboxOwnershipRegistry) -> None:
        registry.record("herta", "sbx-001")
        registry.record("herta", "sbx-002")
        assert registry.list_owned("herta") == {"sbx-001", "sbx-002"}

    def test_multiple_personas(self, registry: SandboxOwnershipRegistry) -> None:
        registry.record("herta", "sbx-001")
        registry.record("alice", "sbx-002")
        assert registry.list_owned("herta") == {"sbx-001"}
        assert registry.list_owned("alice") == {"sbx-002"}

    def test_empty_persona(self, registry: SandboxOwnershipRegistry) -> None:
        assert registry.list_owned("nonexistent") == set()


class TestRemove:
    def test_remove_existing(self, registry: SandboxOwnershipRegistry) -> None:
        registry.record("herta", "sbx-001")
        registry.remove("sbx-001")
        assert registry.list_owned("herta") == set()

    def test_remove_nonexistent(self, registry: SandboxOwnershipRegistry) -> None:
        registry.remove("sbx-999")  # Should not raise


class TestCleanupPersona:
    def test_cleanup(self, registry: SandboxOwnershipRegistry) -> None:
        registry.record("herta", "sbx-001")
        registry.record("herta", "sbx-002")
        registry.record("alice", "sbx-003")
        count = registry.cleanup_persona("herta")
        assert count == 2
        assert registry.list_owned("herta") == set()
        assert registry.list_owned("alice") == {"sbx-003"}


class TestPersistence:
    def test_persists_across_instances(self, tmp_path: Path) -> None:
        r1 = SandboxOwnershipRegistry(str(tmp_path))
        r1.record("herta", "sbx-001")

        r2 = SandboxOwnershipRegistry(str(tmp_path))
        assert r2.list_owned("herta") == {"sbx-001"}

    def test_file_created(self, tmp_path: Path) -> None:
        r1 = SandboxOwnershipRegistry(str(tmp_path))
        r1.record("herta", "sbx-001")
        assert (tmp_path / _REGISTRY_FILENAME).exists()


class TestGetRegistry:
    def test_singleton_same_dir(self, tmp_path: Path) -> None:
        r1 = get_registry(str(tmp_path))
        r2 = get_registry(str(tmp_path))
        assert r1 is r2

    def test_new_dir_creates_new_instance(self, tmp_path: Path) -> None:
        r1 = get_registry(str(tmp_path / "a"))
        r2 = get_registry(str(tmp_path / "b"))
        assert r1 is not r2
