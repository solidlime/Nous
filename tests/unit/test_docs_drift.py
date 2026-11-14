"""scripts/check_docs_drift.py / search_quality_smoke.py のゲート自己検証。

ドキュメント同期そのものは CI の `docs-drift` ジョブが回す。ここでは抽出ロジックが
実装を読めていること（0 件抽出の見逃し防止）だけを固定する。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / "scripts" / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_path_normalization_treats_param_names_as_equal():
    drift = _load("check_docs_drift")
    assert drift._normalize_path("/api/chat/{persona}/sessions") == drift._normalize_path(
        "/api/chat/{persona_name}/sessions"
    )
    assert drift._normalize_path("/") == "/"


def test_extractors_find_real_implementation():
    drift = _load("check_docs_drift")
    tools = drift.code_mcp_tools()
    assert {"memory_search", "session_begin", "wiki_write"} <= tools
    endpoints = drift.code_http_endpoints()
    assert ("GET", "/api/search/{}") in endpoints
    assert {"NOUS_QDRANT__URL", "NOUS_SEARCH__INJECTION_MAX_BM25"} <= drift.settings_env_keys()


def test_current_repo_has_no_documented_phantoms():
    drift = _load("check_docs_drift")
    assert not drift.doc_mcp_tools() - drift.code_mcp_tools()
    assert not drift.doc_http_endpoints() - drift.code_http_endpoints()
    assert not drift.doc_env_keys() - (drift.settings_env_keys() | drift.ENV_ONLY)
