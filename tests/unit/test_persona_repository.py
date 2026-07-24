"""Tests for PersonaRepository protocol interface."""

from __future__ import annotations

from typing import Protocol

import pytest

from nous.domain.persona.repository import PersonaRepository
from nous.infrastructure.sqlite.persona_repo import (
    SQLitePersonaRepository,
)


class TestPersonaRepositoryInterface:
    """Verify the protocol interface contract."""

    def test_persona_repository_is_protocol(self):
        """PersonaRepository should be a Protocol, not ABC."""
        assert issubclass(PersonaRepository, Protocol)

    def test_sqlite_repo_conforms_to_interface(self, sqlite_conn):
        """SQLitePersonaRepository should be recognized via runtime_checkable."""
        repo = SQLitePersonaRepository(sqlite_conn)
        assert isinstance(repo, PersonaRepository)
