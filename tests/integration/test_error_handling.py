"""Tests for error responses: no exception detail leakage."""

import importlib
import inspect
import pkgutil


def _all_router_source(module) -> str:
    """Module source; for packages, concatenate all submodules (routers may be split)."""
    parts = [inspect.getsource(module)]
    if hasattr(module, "__path__"):
        for m in pkgutil.walk_packages(module.__path__, module.__name__ + "."):
            parts.append(inspect.getsource(importlib.import_module(m.name)))
    return "\n".join(parts)


def test_routers_import_without_error():
    """全ルーターが正しくインポートできること（構文エラーチェック）。"""
    from nous.api.http.routers import admin, item, memory, persona, search

    assert admin is not None
    assert item is not None
    assert memory is not None
    assert persona is not None
    assert search is not None


def test_error_response_does_not_leak_exception_details():
    """各ルーターが str(exc) をレスポンスに含めていないことを確認。"""
    from nous.api.http.routers import admin, item, memory, persona, search

    for module in (admin, item, memory, persona, search):
        source = _all_router_source(module)
        assert '"error": str(exc)' not in source, f"{module.__name__} leaks exception detail via str(exc)"


def test_internal_server_error_string_present_in_routers():
    """各ルーターに 'Internal server error' フォーマットが使われている。"""
    from nous.api.http.routers import admin, item, memory, persona, search

    for module in (admin, item, memory, persona, search):
        source = _all_router_source(module)
        assert "Internal server error" in source, f"{module.__name__} missing 'Internal server error' error response"
