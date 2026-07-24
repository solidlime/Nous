from __future__ import annotations


class DomainError(Exception):
    """Base error for all domain errors."""


class MemoryNotFoundError(DomainError):
    """Memory entry not found."""


class MemoryValidationError(DomainError):
    """Memory validation failed."""


class PersonaNotFoundError(DomainError):
    """Persona not found."""


class PersonaValidationError(DomainError):
    """Persona validation failed."""


class ItemNotFoundError(DomainError):
    """Item not found."""


class ItemValidationError(DomainError):
    """Item validation failed."""


class SearchError(DomainError):
    """Search operation failed."""


class RepositoryError(DomainError):
    """Repository operation failed."""


class MigrationError(DomainError):
    """Database migration failed."""


class ConfigError(DomainError):
    """Configuration error."""


class DuplicateMemoryError(DomainError):
    """Memory content duplicates an existing memory."""

    def __init__(
        self,
        message: str,
        duplicate_key: str | None = None,
        similar_to: list[dict] | None = None,
    ) -> None:
        self.duplicate_key = duplicate_key
        self.similar_to = similar_to
        super().__init__(message)


class VectorStoreError(DomainError):
    """Vector store operation failed."""
