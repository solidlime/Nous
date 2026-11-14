#!/usr/bin/env python3
"""Docs / 実装ドリフト検知（軽量・依存なし）.

実装側のソースから次を抽出し、ドキュメントと突き合わせる:

1. MCP ツール: `nous/api/mcp/tools.py` の `@_tool("...")` ↔ `docs/architecture.md` の「MCP ツール一覧」
2. HTTP エンドポイント: `mcp.custom_route("...", methods=[...])` ↔ `docs/http_api_reference.md` の `### \\`METHOD /path\\``
3. 設定 env キー: `Settings`（pydantic）から導出 ↔ `docs/architecture.md` / `.env.example` の `NOUS_*`
4. live 文書のパス:行 参照と相対リンク: `docs/archive/` `docs/releases/` `docs/evidence/`
   配下（frozen）は対象外。live 文書の `` `path:line` `` がリポジトリ内で解決できない、
   行番号が実ファイルの行数を超える、相対リンクが存在しない → error
   複数行は `` `path:a-b` `` のみ対応（`` `path:a-b,c` `` は非マッチ）

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
DOCS_DIR = REPO_ROOT / "docs"
# docs 直下のこの名前のディレクトリ配下は「凍結された記録」なので検査しない。
FROZEN_TOP = {"archive", "releases", "evidence"}

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


def live_docs() -> list[Path]:
    """実装と同期させる義務のある文書（frozen を除く）。"""
    docs = [REPO_ROOT / "README.md"] if (REPO_ROOT / "README.md").exists() else []
    for path in DOCS_DIR.rglob("*.md"):
        if path.relative_to(DOCS_DIR).parts[0] not in FROZEN_TOP:
            docs.append(path)
    return sorted(docs)


_DOC_REF_RE = re.compile(
    r"`((?:[A-Za-z0-9_./-]+/)?[A-Za-z0-9_.-]+\.(?:py|ts|js|sh|json|yml|yaml|md|toml|css|html|sql)):(\d+)(?:-(\d+))?`"
)
_DOC_LINK_RE = re.compile(r"\]\(([^)\s]+)\)")
_SKIP_LINK_PREFIXES = ("http://", "https://", "mailto:", "#", "/")


def _repo_index() -> dict[str, list[Path]]:
    """basename -> パス一覧（スラッシュ無しの bare `mod.py` 参照を解決するため）。"""
    index: dict[str, list[Path]] = {}
    skip = {".git", "node_modules", ".venv", ".mypy_cache", "output"}
    for path in REPO_ROOT.rglob("*"):
        if not path.is_file() or skip & set(path.parts):
            continue
        index.setdefault(path.name, []).append(path)
    return index


def _line_count(path: Path) -> int | None:
    try:
        return len(path.read_text(encoding="utf-8").splitlines())
    except (OSError, UnicodeDecodeError):
        return None


def check_doc_references() -> tuple[list[str], int, int]:
    """live 文書の `path:line` 参照と相対リンクを検証する.

    戻り値: (errors, 検査した参照数, 検査したリンク数)
    """
    errors: list[str] = []
    index: dict[str, list[Path]] | None = None  # 最初の未解決参照まで構築しない
    checked_refs = 0
    checked_links = 0
    for doc in live_docs():
        doc_rel = doc.relative_to(REPO_ROOT).as_posix()
        for lineno, line in enumerate(doc.read_text(encoding="utf-8").splitlines(), 1):
            for match in _DOC_REF_RE.finditer(line):
                checked_refs += 1
                rel = match.group(1)
                target = REPO_ROOT / rel
                if not target.exists():
                    # スラッシュ付きは移動・削除の検出が目的。basename で救済すると偽陰性になる。
                    if "/" in rel:
                        errors.append(f"doc ref not found: {doc_rel}:{lineno} {rel}")
                        continue
                    if index is None:
                        index = _repo_index()
                    candidates = index.get(Path(rel).name, [])
                    if len(candidates) != 1:
                        kind = "ambiguous" if candidates else "not found"
                        errors.append(f"doc ref {kind}: {doc_rel}:{lineno} {rel}")
                        continue
                    target = candidates[0]
                n = _line_count(target)
                if n is None:
                    continue
                start = int(match.group(2))
                end = int(match.group(3) or start)
                if not 1 <= start <= end or end > n:
                    # 逆順は end が範囲内でも error なので、書かれた範囲をそのまま出す
                    shown = f"{rel}:{end}" if start <= end else f"{rel}:{start}-{end}"
                    errors.append(f"doc ref line out of range: {doc_rel}:{lineno} {shown} (file has {n} lines)")
            for match in _DOC_LINK_RE.finditer(line):
                link = match.group(1)
                if link.startswith(_SKIP_LINK_PREFIXES):
                    continue
                checked_links += 1
                link_path = link.split("#")[0]
                if link_path and not (doc.parent / link_path).resolve().exists():
                    errors.append(f"doc link broken: {doc_rel}:{lineno} {link}")
    return errors, checked_refs, checked_links


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

    # 4. live 文書のパス:行 参照と相対リンク（frozen は対象外）
    docs = live_docs()
    doc_errors, doc_refs, doc_links = check_doc_references()
    errors.extend(doc_errors)

    if args.verbose:
        print(f"live docs: {len(docs)}")
        for doc in docs:
            print(f"  {doc.relative_to(REPO_ROOT).as_posix()}")
        print(f"known undocumented HTTP endpoints: {len(undocumented_str)}")
        for endpoint in sorted(undocumented_str):
            print(f"  {endpoint}")
    for warning in warnings:
        print(f"WARN: {warning}", file=sys.stderr)
    if errors:
        for error in errors:
            print(f"DRIFT: {error}", file=sys.stderr)
        raise SystemExit(1)
    print(
        f"docs drift: OK (mcp_tools={len(tools_code)}, http_routes={len(http_code)}, env_docs={len(env_doc)}, "
        f"live_docs={len(docs)}, doc_refs={doc_refs}, doc_links={doc_links})"
    )


if __name__ == "__main__":
    main()
