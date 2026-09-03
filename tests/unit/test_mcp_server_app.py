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
