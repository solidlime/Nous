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


def test_live_docs_excludes_frozen():
    drift = _load("check_docs_drift")
    live = drift.live_docs()
    rels = [path.relative_to(drift.REPO_ROOT).as_posix() for path in live]
    assert "README.md" in rels
    assert "docs/README.md" in rels
    frozen = "docs/archive/reviews/2026-09-19-parity-baseline.md"
    assert (drift.REPO_ROOT / frozen).exists()
    assert frozen not in rels


def test_doc_reference_checks_detect_breakage(tmp_path, monkeypatch):
    drift = _load("check_docs_drift")
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "mod.py").write_text("a = 1\nb = 2\nc = 3\n", encoding="utf-8")
    (tmp_path / "pkg" / "uniq.py").write_text("x = 1\n", encoding="utf-8")
    for name in ("a", "b"):
        (tmp_path / name).mkdir()
        (tmp_path / name / "dup.py").write_text("x = 1\n", encoding="utf-8")
    docs = tmp_path / "docs"
    (docs / "archive").mkdir(parents=True)
    (docs / "live.md").write_text(
        "ok `pkg/mod.py:3`\n"
        "missing `pkg/nope.py:1`\n"
        "over `pkg/mod.py:2-99`\n"
        "broken [x](nope.md)\n"
        "uniq `uniq.py:1`\n"
        "dup `dup.py:1`\n"
        "slash `gone/mod.py:1`\n"
        "past `pkg/mod.py:4`\n"
        "rev `pkg/mod.py:3-1`\n"
        "zero `pkg/mod.py:0`\n",
        encoding="utf-8",
    )
    (docs / "archive" / "old.md").write_text("frozen `pkg/nope.py:1` [y](nope.md)\n", encoding="utf-8")
    monkeypatch.setattr(drift, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(drift, "DOCS_DIR", docs)

    errors, refs, links = drift.check_doc_references()

    assert (refs, links) == (9, 1)
    assert "doc ref not found: docs/live.md:2 pkg/nope.py" in errors
    assert "doc ref line out of range: docs/live.md:3 pkg/mod.py:99 (file has 3 lines)" in errors
    assert "doc link broken: docs/live.md:4 nope.md" in errors
    assert not [error for error in errors if "uniq.py" in error]
    assert "doc ref ambiguous: docs/live.md:6 dup.py" in errors
    assert "doc ref not found: docs/live.md:7 gone/mod.py" in errors
    assert "doc ref line out of range: docs/live.md:8 pkg/mod.py:4 (file has 3 lines)" in errors
    assert "doc ref line out of range: docs/live.md:9 pkg/mod.py:3-1 (file has 3 lines)" in errors
    assert "doc ref line out of range: docs/live.md:10 pkg/mod.py:0 (file has 3 lines)" in errors
    assert not [error for error in errors if "old.md" in error]


def test_current_repo_has_no_live_doc_drift():
    drift = _load("check_docs_drift")
    assert drift.check_doc_references()[0] == []
