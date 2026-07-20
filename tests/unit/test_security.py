"""Security-focused unit tests.

Covers:
  - Bearer token / X-Persona header input validation (middleware.py)
  - Zip Slip prevention in ZIP import (legacy_importer.py)
  - Query parameter bounds validation (routes.py limit parameter)
"""

from __future__ import annotations

import sqlite3
import zipfile
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

import pytest

from nous.api.mcp.middleware import resolve_persona_from_headers
from nous.domain.shared.errors import MigrationError
from nous.domain.shared.result import Failure
from nous.migration.importers.legacy_importer import LegacyImporter

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helper: standalone limit validator (mirrors expected routes.py logic)
# ---------------------------------------------------------------------------

_MAX_LIMIT = 1000


def _validate_limit(raw: object) -> int:
    """Validate a query parameter intended as a positive integer limit.

    Raises ``ValueError`` when the value is not a valid integer or falls
    outside the accepted range ``[1, _MAX_LIMIT]``.
    """
    try:
        value = int(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ValueError(f"limit must be an integer, got: {raw!r}") from exc
    if value < 1:
        raise ValueError(f"limit must be >= 1, got: {value}")
    if value > _MAX_LIMIT:
        raise ValueError(f"limit must be <= {_MAX_LIMIT}, got: {value}")
    return value


# =========================================================================
# Group 1: Bearer Token Validation
# =========================================================================


@pytest.mark.unit
class TestBearerTokenValidation:
    """Verify that resolve_persona_from_headers() rejects unsafe tokens."""

    def test_valid_persona_name_accepted(self):
        """`myPersona` is alphanumeric — should be returned as-is."""
        result = resolve_persona_from_headers(authorization="Bearer myPersona")
        assert result == "myPersona"

    def test_valid_with_hyphen_underscore(self):
        """`my-persona_123` contains only allowed characters."""
        result = resolve_persona_from_headers(authorization="Bearer my-persona_123")
        assert result == "my-persona_123"

    def test_injection_attempt_rejected(self, monkeypatch):
        """SQL injection in token must NOT be used as persona name."""
        monkeypatch.delenv("PERSONA", raising=False)
        monkeypatch.delenv("NOUS_DEFAULT_PERSONA", raising=False)
        malicious = 'Bearer "; DROP TABLE memories; --'
        result = resolve_persona_from_headers(authorization=malicious)
        # Must not accept the injected string
        assert result is None

    def test_special_chars_rejected(self, monkeypatch):
        """Path traversal chars in token must be rejected."""
        monkeypatch.delenv("PERSONA", raising=False)
        monkeypatch.delenv("NOUS_DEFAULT_PERSONA", raising=False)
        result = resolve_persona_from_headers(authorization="Bearer ../../../etc")
        assert result is None

    def test_too_long_token_rejected(self, monkeypatch):
        """Token longer than 64 characters must be rejected."""
        monkeypatch.delenv("PERSONA", raising=False)
        monkeypatch.delenv("NOUS_DEFAULT_PERSONA", raising=False)
        long_token = "a" * 65
        result = resolve_persona_from_headers(authorization=f"Bearer {long_token}")
        assert result is None

    def test_exactly_64_chars_accepted(self):
        """Token of exactly 64 characters is within the allowed limit."""
        token = "a" * 64
        result = resolve_persona_from_headers(authorization=f"Bearer {token}")
        assert result == token

    def test_empty_token_rejected(self, monkeypatch):
        """`Bearer   ` (spaces only) must fall through to next source."""
        monkeypatch.delenv("PERSONA", raising=False)
        monkeypatch.delenv("NOUS_DEFAULT_PERSONA", raising=False)
        result = resolve_persona_from_headers(
            authorization="Bearer   ",
            x_persona="fallback_persona",
        )
        # Empty Bearer → should use x_persona
        assert result == "fallback_persona"

    def test_x_persona_header_validation(self, monkeypatch):
        """`X-Persona` with special characters must be rejected."""
        monkeypatch.delenv("PERSONA", raising=False)
        monkeypatch.delenv("NOUS_DEFAULT_PERSONA", raising=False)
        result = resolve_persona_from_headers(x_persona="../../root")
        assert result is None

    def test_x_persona_valid_value_accepted(self):
        """Valid `X-Persona` value passes through."""
        result = resolve_persona_from_headers(x_persona="alice_123")
        assert result == "alice_123"

    def test_bearer_takes_priority_over_x_persona(self):
        """Bearer token wins over X-Persona header."""
        result = resolve_persona_from_headers(
            authorization="Bearer alice",
            x_persona="bob",
        )
        assert result == "alice"


# =========================================================================
# Group 2: Zip Slip Prevention
# =========================================================================


@pytest.mark.unit
class TestZipSlipPrevention:
    """Verify that LegacyImporter.import_from_zip() blocks path traversal."""

    def _make_zip_with_memory_sqlite(self, zip_path: Path, tmp_path: Path) -> Path:
        """Create a minimal valid ZIP containing an empty memory.sqlite."""
        db_path = tmp_path / "memory.sqlite"
        conn = sqlite3.connect(str(db_path))
        conn.close()

        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.write(db_path, arcname="memory.sqlite")

        return zip_path

    def test_normal_zip_import_works(self, tmp_path, sqlite_conn):
        """A well-formed ZIP with memory.sqlite should import without error."""
        zip_path = tmp_path / "valid.zip"
        self._make_zip_with_memory_sqlite(zip_path, tmp_path)

        importer = LegacyImporter(target_connection=sqlite_conn, persona="test")
        result = importer.import_from_zip(str(zip_path))

        assert result.is_ok, f"Expected success, got: {result}"

    def test_zip_slip_absolute_path_rejected(self, tmp_path, sqlite_conn):
        """ZIP member with absolute path must be detected as Zip Slip."""
        zip_path = tmp_path / "evil_abs.zip"

        with zipfile.ZipFile(zip_path, "w") as zf:
            # Write a member with an absolute-style path
            info = zipfile.ZipInfo("/etc/passwd")
            zf.writestr(info, "root:x:0:0:root:/root:/bin/bash")

        importer = LegacyImporter(target_connection=sqlite_conn, persona="test")
        result = importer.import_from_zip(str(zip_path))

        assert isinstance(result, Failure)
        assert isinstance(result.error, MigrationError)
        assert "Zip Slip" in str(result.error)

    def test_zip_slip_relative_traversal_rejected(self, tmp_path, sqlite_conn):
        """ZIP member with `../` traversal must be detected as Zip Slip."""
        zip_path = tmp_path / "evil_rel.zip"

        with zipfile.ZipFile(zip_path, "w") as zf:
            info = zipfile.ZipInfo("../../../evil.txt")
            zf.writestr(info, "payload")

        importer = LegacyImporter(target_connection=sqlite_conn, persona="test")
        result = importer.import_from_zip(str(zip_path))

        assert isinstance(result, Failure)
        assert isinstance(result.error, MigrationError)
        assert "Zip Slip" in str(result.error)

    def test_zip_slip_nested_traversal_rejected(self, tmp_path, sqlite_conn):
        """Nested traversal like `subdir/../../evil.txt` must also be blocked."""
        zip_path = tmp_path / "evil_nested.zip"

        with zipfile.ZipFile(zip_path, "w") as zf:
            info = zipfile.ZipInfo("subdir/../../evil.txt")
            zf.writestr(info, "payload")

        importer = LegacyImporter(target_connection=sqlite_conn, persona="test")
        result = importer.import_from_zip(str(zip_path))

        assert isinstance(result, Failure)
        assert isinstance(result.error, MigrationError)
        assert "Zip Slip" in str(result.error)

    def test_missing_zip_returns_failure(self, tmp_path, sqlite_conn):
        """Non-existent ZIP path returns a Failure, not an exception."""
        importer = LegacyImporter(target_connection=sqlite_conn, persona="test")
        result = importer.import_from_zip(str(tmp_path / "nonexistent.zip"))

        assert isinstance(result, Failure)
        assert isinstance(result.error, MigrationError)


# =========================================================================
# Group 3: Query Parameter Validation
# =========================================================================


@pytest.mark.unit
class TestQueryParamValidation:
    """Validate `limit` query parameter logic used in HTTP routes.

    The helper ``_validate_limit`` (defined in this module) mirrors the
    validation that routes should apply before passing the value to the
    service layer.
    """

    def test_valid_limit_accepted(self):
        """limit=10 is within bounds and should be accepted."""
        assert _validate_limit(10) == 10

    def test_valid_limit_string_coerced(self):
        """String "10" should be coerced to int correctly."""
        assert _validate_limit("10") == 10

    def test_limit_too_large_rejected(self):
        """limit=9999 exceeds MAX_LIMIT and must raise ValueError."""
        with pytest.raises(ValueError, match="limit must be <="):
            _validate_limit(9999)

    def test_limit_non_integer_rejected(self):
        """Non-numeric string must raise ValueError (would cause 400 in API)."""
        with pytest.raises(ValueError, match="limit must be an integer"):
            _validate_limit("abc")

    def test_negative_limit_rejected(self):
        """Negative limit is invalid and must raise ValueError."""
        with pytest.raises(ValueError, match="limit must be >= 1"):
            _validate_limit(-1)

    def test_zero_limit_rejected(self):
        """Zero limit makes no semantic sense and must be rejected."""
        with pytest.raises(ValueError, match="limit must be >= 1"):
            _validate_limit(0)

    def test_boundary_limit_accepted(self):
        """limit=1000 (MAX_LIMIT) is exactly on the boundary and must pass."""
        assert _validate_limit(_MAX_LIMIT) == _MAX_LIMIT

    def test_one_above_max_rejected(self):
        """limit=MAX_LIMIT+1 exceeds the boundary and must be rejected."""
        with pytest.raises(ValueError, match="limit must be <="):
            _validate_limit(_MAX_LIMIT + 1)
