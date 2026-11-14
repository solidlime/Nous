#!/usr/bin/env python3
"""Docs / 実装ドリフト検知（軽量・依存なし）.

実装側のソースから次を抽出し、ドキュメントと突き合わせる:

1. MCP ツール: `nous/api/mcp/tools.py` の `@_tool("...")` ↔ `docs/architecture.md` の「MCP ツール一覧」
2. HTTP エンドポイント: `mcp.custom_route("...", methods=[...])` ↔ `docs/http_api_reference.md` の `### \\`METHOD /path\\``
3. 設定 env キー: `Settings`（pydantic）から導出 ↔ `docs/architecture.md` / `.env.example` の `NOUS_*`

ルール:
- ドキュメントにあるが実装に無い（幽霊エンドポイント/ツール/env）→ error
- 実装にあるがドキュメントに無い HTTP エンドポイント → 既知の未記載分は
  `scripts/docs_drift_baseline.json` に記録し、**新規**未記載だけ error
- MCP ツールは双方向で error（一覧は網羅が前提）

使い方:
  python scripts/check_docs_drift.py               # チェック（失敗で exit 1）
  python scripts/check_docs_drift.py --verbose     # 未記載の既知分も表示
  python scripts/check_docs_drift.py --write-baseline  # 未記載 HTTP 一覧を baseline に保存
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from json import loads
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BASELINE_PATH = Path(__file__).with_name("docs_drift_baseline.json")

MCP_SRC = REPO_ROOT / "nous" / "api" / "mcp" / "tools.py"
HTTP_SRC_DIR = REPO_ROOT / "nous" / "api" / "http"
ARCH_DOC = REPO_ROOT / "docs" / "architecture.md"
HTTP_DOC = REPO_ROOT / "docs" / "http_api_reference.md"
ENV_DOCS = [ARCH_DOC, REPO_ROOT / ".env.example"]

# Settings を持たないがコードが直接読む env と、docs に残す運用上の名前。
ENV_ONLY = {
    "NOUS_TOOL_DESCRIPTION_OVERRIDE",
    "NOUS_PERSONAS",  # docker-compose で opensandbox-mcp サービス群を定義する時の手動名（Nous は読まない）
}

_PATH_PARAM = re.compile(r"\{[^}/]+\}")


def _normalize_path(path: str) -> str:
    """`/api/x/{persona}` と `/api/x/{name}` を同一視する。"""
    return _PATH_PARAM.sub("{}", path.rstrip("/") or "/")


def code_mcp_tools() -> set[str]:
    text = MCP_SRC.read_text(encoding="utf-8")
    return set(re.findall(r'@_tool\("([a-z][a-z0-9_]*)"\)', text))


def _section(text: str, heading: str) -> str:
    start = text.find(heading)
    if start == -1:
        return ""
    rest = text[start + len(heading) :]
    end = rest.find("\n## ")
    return rest if end == -1 else rest[:end]


def doc_mcp_tools() -> set[str]:
    section = _section(ARCH_DOC.read_text(encoding="utf-8"), "## MCP ツール一覧")
    tools: set[str] = set()
    for line in section.splitlines():
        if line.startswith("|") and (match := re.search(r"`([a-z][a-z0-9_]*)`", line)):
            tools.add(match.group(1))
    return tools


_ROUTE_RE = re.compile(r'custom_route\(\s*"([^"]+)"\s*,\s*methods=\[([^\]]*)\]', re.DOTALL)
_METHOD_RE = re.compile(r'"([A-Z]+)"')


def code_http_endpoints() -> set[tuple[str, str]]:
    endpoints: set[tuple[str, str]] = set()
    for path in HTTP_SRC_DIR.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        for raw_path, raw_methods in _ROUTE_RE.findall(text):
            for method in _METHOD_RE.findall(raw_methods):
                endpoints.add((method, _normalize_path(raw_path)))
    return endpoints


_DOC_ENDPOINT_RE = re.compile(r"^### `(GET|POST|PUT|DELETE|PATCH) ([^`]+)`", re.MULTILINE)


def doc_http_endpoints() -> set[tuple[str, str]]:
    text = HTTP_DOC.read_text(encoding="utf-8")
    return {(m, _normalize_path(p)) for m, p in _DOC_ENDPOINT_RE.findall(text)}


def settings_env_keys() -> set[str]:
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    try:
        from nous.config.settings import Settings
    except ImportError as e:  # pragma: no cover - CI installs requirements-prod
        raise SystemExit(f"cannot import Settings (install requirements-prod): {e}") from e
    from pydantic import BaseModel

    keys = {"NOUS_DATA_ROOT"}  # main.py / fts_tokenize.py が Settings より先に読む
    for name, field in Settings.model_fields.items():
        if isinstance(field.alias, str) and field.alias.startswith("NOUS_"):
            keys.add(field.alias)
        keys.add(f"NOUS_{name.upper()}")
        annotation = field.annotation
        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            for sub in annotation.model_fields:
                keys.add(f"NOUS_{name.upper()}__{sub.upper()}")
    return keys


_ENV_RE = re.compile(r"NOUS_[A-Z0-9_]+")


def doc_env_keys() -> set[str]:
    keys: set[str] = set()
    for path in ENV_DOCS:
        keys.update(_ENV_RE.findall(path.read_text(encoding="utf-8")))
    return keys


def load_baseline() -> set[str]:
    """baseline JSON を読む（無ければ空）。"""
    try:
        raw = BASELINE_PATH.read_text(encoding="utf-8") if BASELINE_PATH.exists() else "{}"
        data = loads(raw)
    except (OSError, ValueError) as e:
        raise SystemExit(f"invalid baseline {BASELINE_PATH}: {e}") from e
    return set(data.get("undocumented_http_endpoints", []))


def _fmt_endpoints(items: set[tuple[str, str]] | set[str]) -> list[str]:
    return sorted(item if isinstance(item, str) else f"{item[0]} {item[1]}" for item in items)


def main() -> None:
    ap = argparse.ArgumentParser(description="Docs / 実装ドリフト検知")
    ap.add_argument("--verbose", action="store_true", help="既知の未記載エンドポイントも表示")
    ap.add_argument("--write-baseline", action="store_true", help="未記載 HTTP 一覧を baseline に保存して終了")
    args = ap.parse_args()

    errors: list[str] = []
    warnings: list[str] = []

    # 1. MCP tools（双方向）
    tools_code = code_mcp_tools()
    tools_doc = doc_mcp_tools()
    if missing_doc := sorted(tools_code - tools_doc):
        errors.append(f"MCP tools not in docs/architecture.md: {', '.join(missing_doc)}")
    if phantom := sorted(tools_doc - tools_code):
        errors.append(f"MCP tools documented but not registered: {', '.join(phantom)}")

    # 2. HTTP endpoints
    http_code = code_http_endpoints()
    http_doc = doc_http_endpoints()
    if phantom_http := http_doc - http_code:
        errors.append("HTTP endpoints documented but not routed:\n  " + "\n  ".join(_fmt_endpoints(phantom_http)))
    undocumented = http_code - http_doc
    baseline = load_baseline()
    undocumented_str = {f"{m} {p}" for m, p in undocumented}
    if args.write_baseline:
        BASELINE_PATH.write_text(
            json.dumps({"undocumented_http_endpoints": sorted(undocumented_str)}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"wrote {BASELINE_PATH.relative_to(REPO_ROOT)} ({len(undocumented_str)} endpoints)")
        return
    if new := sorted(undocumented_str - baseline):
        errors.append("HTTP endpoints not documented and not in baseline:\n  " + "\n  ".join(new))
    if stale := sorted(baseline - undocumented_str):
        warnings.append(
            "baseline entries now documented/removed (regenerate with --write-baseline):\n  " + "\n  ".join(stale)
        )

    # 3. 設定 env キー（ドキュメント → 実装）
    env_doc = doc_env_keys()
    env_code = settings_env_keys() | ENV_ONLY
    if phantom_env := sorted(env_doc - env_code):
        errors.append(f"env vars documented but not in Settings/ENV_ONLY: {', '.join(phantom_env)}")

    if args.verbose:
        print(f"known undocumented HTTP endpoints: {len(undocumented_str)}")
        for endpoint in sorted(undocumented_str):
            print(f"  {endpoint}")
    for warning in warnings:
        print(f"WARN: {warning}", file=sys.stderr)
    if errors:
        for error in errors:
            print(f"DRIFT: {error}", file=sys.stderr)
        raise SystemExit(1)
    print(f"docs drift: OK (mcp_tools={len(tools_code)}, http_routes={len(http_code)}, env_docs={len(env_doc)})")


if __name__ == "__main__":
    main()
