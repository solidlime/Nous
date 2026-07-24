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


class VectorStoreError(DomainError):
    """Vector store operation failed."""
