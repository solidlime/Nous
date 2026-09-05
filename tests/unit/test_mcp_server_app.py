"""Runner-compat tests for MemoryFastMCP app factories.

v2 runners call these factories WITH kwargs
(`run_streamable_http_async` passes streamable_http_path/json_response/...,
`run_sse_async` passes sse_path/message_path/...).
A zero-arg-only override breaks real serving while unit tests stay green —
this module pins the runner call shape. (Regression: TypeError
`streamable_http_app() got an unexpected keyword argument 'streamable_http_path'`.)
"""

from __future__ import annotations

import pytest
from starlette.applications import Starlette
from starlette.middleware.cors import CORSMiddleware
from starlette.testclient import TestClient

from nous.config.settings import CorsConfig, Settings
from nous.main import MemoryFastMCP

pytestmark = pytest.mark.unit


def _make_server() -> MemoryFastMCP:
    return MemoryFastMCP("test")


class TestRunnerCompat:
    def test_streamable_http_app_accepts_runner_kwargs(self):
        """Runner kwargs must not TypeError, and override middleware must apply."""
        import nous.main as main_mod

        settings = Settings(cors=CorsConfig(allowed_origins=["*"]))
        original_getter = main_mod.get_settings
        main_mod.get_settings = lambda: settings  # type: ignore[method-assign]
        try:
            app = _make_server().streamable_http_app(
                streamable_http_path="/mcp",
                json_response=True,
                stateless_http=True,
                host="127.0.0.1",
            )
        finally:
            main_mod.get_settings = original_getter
        assert isinstance(app, Starlette)
        assert CORSMiddleware in [m.cls for m in app.user_middleware]

    def test_sse_app_accepts_runner_kwargs(self):
        """Runner kwargs must not TypeError, and override middleware must apply."""
        import nous.main as main_mod

        settings = Settings(cors=CorsConfig(allowed_origins=["*"]))
        original_getter = main_mod.get_settings
        main_mod.get_settings = lambda: settings  # type: ignore[method-assign]
        try:
            app = _make_server().sse_app(
                sse_path="/sse",
                message_path="/messages/",
                host="127.0.0.1",
            )
        finally:
            main_mod.get_settings = original_getter
        assert isinstance(app, Starlette)
        assert CORSMiddleware in [m.cls for m in app.user_middleware]


class TestTransportSecurityAllowlist:
    """SDK DNS-rebinding protection must allow the docker service name.

    Regression: mcp-hub → Host: nous:26262 got 421 because the SDK default
    allowlist is localhost-only. Protection itself must stay ON (unknown
    hosts still 421).
    """

    def _app(self) -> Starlette:
        import nous.main as main_mod

        settings = Settings(cors=CorsConfig(allowed_origins=["*"]))
        original_getter = main_mod.get_settings
        main_mod.get_settings = lambda: settings  # type: ignore[method-assign]
        try:
            return _make_server().streamable_http_app(
                json_response=True,
                stateless_http=True,
            )
        finally:
            main_mod.get_settings = original_getter

    @staticmethod
    def _post_mcp(client: TestClient, host: str):
        return client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "ping", "params": {}},
            headers={
                "host": host,
                "content-type": "application/json",
                "accept": "application/json, text/event-stream",
            },
        )

    def test_docker_hostname_accepted(self):
        with TestClient(self._app(), raise_server_exceptions=False) as client:
            assert self._post_mcp(client, "nous:26262").status_code != 421

    def test_localhost_still_accepted(self):
        with TestClient(self._app(), raise_server_exceptions=False) as client:
            assert self._post_mcp(client, "localhost:26262").status_code != 421

    def test_unknown_host_still_rejected(self):
        with TestClient(self._app(), raise_server_exceptions=False) as client:
            assert self._post_mcp(client, "evil.example").status_code == 421
