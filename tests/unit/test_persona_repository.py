"""Tests for PersonaRepository abstract interface."""

from __future__ import annotations

import pytest

from nous.domain.persona.repository import PersonaRepository
from nous.infrastructure.sqlite.persona_repo import SQLitePersonaRepository


class TestPersonaRepositoryInterface:
    """Verify the abstract interface contract."""

    def test_cannot_instantiate_abstract(self):
        """PersonaRepository is abstract and cannot be instantiated directly."""
        with pytest.raises(TypeError, match="Can't instantiate abstract class"):
            PersonaRepository()  # type: ignore[abstract]

    def test_sqlite_repo_conforms_to_interface(self, sqlite_conn):
        """SQLitePersonaRepository should be a concrete implementation."""
        repo = SQLitePersonaRepository(sqlite_conn)
        assert isinstance(repo, PersonaRepository)
