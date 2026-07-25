"""Pact consumer-driven contract test fixtures — function-scoped.

Each test function gets its own Pact instance to avoid Pact FFI state
conflicts (a Pact instance cannot be reused after serve()).
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from pact import Pact

if TYPE_CHECKING:
    from collections.abc import Generator

PACT_DIR = Path(__file__).parent / "pacts"


@pytest.fixture
def pact() -> Generator[Pact, None, None]:
    """Create a Pact instance for a single consumer-driven contract test."""
    pact = Pact("nous-mcp-client", "nous-mcp-server").with_specification("V4")
    yield pact
    # Remove leftover pact files from per-test instances to avoid accumulation
    for f in Path(PACT_DIR).glob("nous-mcp-client-nous-mcp-server*.json"):
        f.unlink()


@pytest.fixture
def mcp_request():
    """Build JSON-RPC 2.0 request body for MCP tool calls."""

    def _build(tool_name: str, arguments: dict, id_val: int = 1) -> dict:
        return {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
            "id": id_val,
        }

    return _build
