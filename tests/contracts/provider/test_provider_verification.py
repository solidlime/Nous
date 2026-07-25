"""Provider-side verification of Pact contracts.

Requires a running Nous MCP server at the configured URL.
Marked with ``@pytest.mark.provider_verify`` so it can be skipped
when the provider is not running.
"""

from __future__ import annotations

import os

import pytest
from pact import Verifier

from tests.contracts.provider.conftest import PACT_FILE

# Default provider URL — override via NOUS_PROVIDER_URL env var
PROVIDER_URL = os.environ.get("NOUS_PROVIDER_URL", "http://localhost:8000")
PROVIDER_NAME = "nous-mcp-server"


@pytest.mark.provider_verify
@pytest.mark.skipif(
    os.environ.get("NOUS_PROVIDER_URL") is None,
    reason="Provider verification requires NOUS_PROVIDER_URL env var (e.g. http://localhost:8000)",
)
class TestProviderVerification:
    """Verify that the running Nous MCP server satisfies all consumer pacts."""

    def test_verify_consumer_pacts(self):
        """Verify all consumer-driven contracts against the running provider."""
        verifier = (
            Verifier(PROVIDER_NAME, host="localhost")
            .add_source(str(PACT_FILE))
            .add_transport(
                url=PROVIDER_URL,
                protocol="http",
            )
            .set_error_on_empty_pact(enabled=False)
        )
        result = verifier.verify()

        # If verification failed, pytest will see the exception
        assert result, (
            f"Provider verification failed for {PACT_FILE}"
        )
