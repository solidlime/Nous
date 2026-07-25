"""Provider verification fixtures for Pact contract tests."""

from __future__ import annotations

from pathlib import Path

PACT_DIR = Path(__file__).parent.parent / "pacts"
PACT_FILE = PACT_DIR / "nous-mcp-client-nous-mcp-server.json"
