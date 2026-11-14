#!/usr/bin/env python3
"""Nous の整合バックアップ / リストア / ポータブルエクスポート。

方針と手順は ``docs/backup_restore.md``。バックアップの正本性は
「wiki(ファイル) > SQLite > Qdrant(派生物)」の順で、Zero Inbox 後は
編纂済み知識が wiki、未編纂の生記憶が SQLite、ベクトルはその索引にすぎない。

バックアップは stdlib だけで動く（動いている Nous に対してオンラインで実行可能）。
Qdrant のスナップショット復元だけは multipart アップロードのため qdrant-client を
使う（無い場合は失敗せず、手動コマンドを表示する）。

使い方::

    python scripts/backup_restore.py backup  --data-root ./data --out ./backups
    python scripts/backup_restore.py verify  --backup  ./backups/nous-backup-20260101-030000
    python scripts/backup_restore.py restore --backup  ./backups/nous-backup-... --data-root ./data --force
    python scripts/backup_restore.py export  --data-root ./data --out ./portable.zip --persona herta

終了コード: 0=成功, 1=失敗, 2=Qdrant 抜きの部分バックアップ（--require-qdrant で 1 に昇格）。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, NoReturn

FORMAT_BACKUP = "nous-backup/1"
FORMAT_PORTABLE = "nous-portable/1"
SECRET_HINTS = ("api_key", "apikey", "token", "password", "secret")
# 除外対象（バックアップに含めないもの）。理由も一緒に manifest に残す。
EXCLUDED = {
    "cache/": "再取得可能なモデルキャッシュ",
    "logs/": "揮発ログ",
    "qdrant/": "Qdrant の生データ。稼働中コピーは不整合になるため snapshot API を使う",
    "sudachi/": "同梱辞書（再取得可能）",
    "persona/*/wiki/._*": "書き込み途中の一時ファイル",
}


# ----------------------------------------------------------------------
# 汎用ヘルパ
# ----------------------------------------------------------------------


def log(msg: str) -> None:
    print(msg, flush=True)


def _die(msg: str) -> NoReturn:
    log(f"ERROR: {msg}")
    raise SystemExit(1)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
    except OSError as e:
        _die(f"読み取り失敗 {path}: {e}")
    return h.hexdigest()


def iso_now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def discover_personas(data_root: Path) -> list[str]:
    base = data_root / "persona"
    if not base.is_dir():
        return []
    return sorted(d.name for d in base.iterdir() if d.is_dir() and (d / "memory.sqlite").exists())


def is_secret_key(key: str) -> bool:
    low = key.lower()
    return any(h in low for h in SECRET_HINTS)


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            k: ("***redacted***" if is_secret_key(str(k)) and not isinstance(v, (dict, list)) else redact(v))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value


def load_manifest(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        _die(f"manifest を読めない {path}: {e}")
    if payload.get("format") != FORMAT_BACKUP:
        _die(f"未知のバックアップ形式 {payload.get('format')!r} ({path})")
    return payload


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


# ----------------------------------------------------------------------
# SQLite（WAL 有効でも一貫した複製を取る）
# ----------------------------------------------------------------------


def backup_sqlite(src: Path, dst: Path) -> dict[str, Any]:
    """sqlite3 の backup API でスナップショットを取る（WAL・書き込み中でも一貫）。"""
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.name + ".partial")
    for leftover in (tmp, tmp.with_name(tmp.name + "-wal"), tmp.with_name(tmp.name + "-shm")):
        leftover.unlink(missing_ok=True)
    src_conn = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
    try:
        dst_conn = sqlite3.connect(str(tmp))
        try:
            src_conn.backup(dst_conn)
            # 複製先は単一ファイルに畳む（-wal を残すと復元先で不整合の元になる）
            dst_conn.execute("PRAGMA journal_mode=DELETE")
            integrity = dst_conn.execute("PRAGMA integrity_check").fetchone()[0]
            rows = _table_counts(dst_conn)
        finally:
            dst_conn.close()
    finally:
        src_conn.close()
    os.replace(tmp, dst)
    return {
        "sha256": sha256_file(dst),
        "bytes": dst.stat().st_size,
        "integrity": integrity,
        "rows": rows,
    }


def _table_counts(conn: sqlite3.Connection) -> dict[str, int]:
    names = [
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' "
            "AND name NOT LIKE '%_fts%' ORDER BY name"
        )
    ]
    counts: dict[str, int] = {}
    for name in names:
        counts[name] = conn.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]  # noqa: S608  # nosec B608 - table names read from sqlite_master
    return counts


def sqlite_integrity(path: Path) -> str:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return conn.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        conn.close()


# ----------------------------------------------------------------------
# wiki（ファイルが正。書き込みは tmp + os.replace で原子的）
# ----------------------------------------------------------------------


def wiki_files(wiki_dir: Path) -> list[Path]:
    if not wiki_dir.is_dir():
        return []
    return sorted(p for p in wiki_dir.rglob("*") if p.is_file() and not p.name.startswith("."))


def copy_wiki(src_dir: Path, dst_dir: Path) -> dict[str, Any]:
    files: dict[str, str] = {}
    pages = 0
    for path in wiki_files(src_dir):
        rel = path.relative_to(src_dir)
        target = dst_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        files[str(rel).replace(os.sep, "/")] = sha256_file(target)
        if rel.suffix == ".md" and rel.name != "index.md":
            pages += 1
    return {"pages": pages, "files": files}


def _clean_stale_tmp(wiki_dir: Path) -> int:
    removed = 0
    for path in wiki_dir.rglob(".*.tmp") if wiki_dir.is_dir() else []:
        path.unlink(missing_ok=True)
        removed += 1
    return removed


# ----------------------------------------------------------------------
# Qdrant（snapshot API 経由。storage ディレクトリの生コピーはしない）
# ----------------------------------------------------------------------


def qdrant_url(explicit: str | None) -> str:
    return explicit or os.environ.get("NOUS_QDRANT__URL") or "http://localhost:6333"


def qdrant_api_key(explicit: str | None) -> str | None:
    return explicit or os.environ.get("NOUS_QDRANT__API_KEY") or None


def _qdrant_request(base: str, path: str, api_key: str | None, method: str = "GET", timeout: int = 60) -> Any:
    req = urllib.request.Request(base.rstrip("/") + path, method=method)
    if api_key:
        req.add_header("api-key", api_key)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310  # nosec B310 - operator-supplied http(s) URL
            body = resp.read()
    except (urllib.error.URLError, OSError) as e:
        raise ConnectionError(f"qdrant request failed {path}: {e}") from e
    try:
        return json.loads(body) if body else None
    except json.JSONDecodeError as e:
        _die(f"qdrant の応答が JSON でない ({path}): {e}")


def _qdrant_download(base: str, path: str, api_key: str | None, dst: Path, timeout: int = 1800) -> None:
    req = urllib.request.Request(base.rstrip("/") + path, method="GET")
    if api_key:
        req.add_header("api-key", api_key)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp, open(dst, "wb") as f:  # noqa: S310  # nosec B310
            shutil.copyfileobj(resp, f, 1 << 20)
    except (urllib.error.URLError, OSError) as e:
        raise ConnectionError(f"qdrant snapshot download failed {path}: {e}") from e


def qdrant_collections(base: str, api_key: str | None, personas: list[str]) -> list[str]:
    payload = _qdrant_request(base, "/collections", api_key)
    names = [c["name"] for c in payload.get("result", {}).get("collections", [])]
    wanted = {f"memory_{p}" for p in personas} | {f"wiki_{p}" for p in personas}
    return sorted(n for n in names if n in wanted)


def snapshot_qdrant(
    base: str,
    api_key: str | None,
    personas: list[str],
    dst_dir: Path,
) -> dict[str, Any]:
    """collection ごとに snapshot を作成→ダウンロード→サーバ側は削除。"""
    collections = qdrant_collections(base, api_key, personas)
    dst_dir.mkdir(parents=True, exist_ok=True)
    snapshots: dict[str, Any] = {}
    for name in collections:
        info = _qdrant_request(base, f"/collections/{name}/snapshots?wait=true", api_key, method="POST", timeout=600)
        snap_name = info["result"]["name"]
        dst = dst_dir / f"{name}.snapshot"
        try:
            _qdrant_download(base, f"/collections/{name}/snapshots/{snap_name}", api_key, dst)
        finally:
            # サーバ側に溜めるとディスクを食うので必ず消す（ローカルに控えはある）
            _qdrant_request(base, f"/collections/{name}/snapshots/{snap_name}", api_key, method="DELETE")
        detail = _qdrant_request(base, f"/collections/{name}", api_key).get("result", {})
        snapshots[name] = {
            "file": f"qdrant/{dst.name}",
            "sha256": sha256_file(dst),
            "bytes": dst.stat().st_size,
            "points": detail.get("points_count"),
            "vector_size": (detail.get("config", {}).get("params", {}).get("vectors") or {}).get("size"),
        }
        log(f"  qdrant: {name} -> {dst.name} ({snapshots[name]['bytes']} bytes)")
    return {"available": True, "url": base, "collections": snapshots}


def restore_qdrant_snapshot(base: str, api_key: str | None, collection: str, path: Path) -> None:
    """snapshot を collection へ復元する（priority=snapshot で既存データを上書き）。"""
    try:
        from qdrant_client import QdrantClient
        from qdrant_client.http import models as qmodels
    except ImportError:
        log(
            "Qdrant snapshot を戻すには qdrant-client が必要。手動なら:\n"
            f"  curl -X POST '{base}/collections/{collection}/snapshots/upload?priority=snapshot' "
            f"-F 'snapshot=@{path}'"
        )
        raise
    client = QdrantClient(url=base, api_key=api_key, timeout=1800)
    try:
        with open(path, "rb") as f:
            client.http.snapshots_api.recover_from_uploaded_snapshot(
                collection_name=collection,
                snapshot=f,
                priority=qmodels.SnapshotPriority.SNAPSHOT,
                wait=True,
            )
    finally:
        client.close()


# ----------------------------------------------------------------------
# backup
# ----------------------------------------------------------------------


def cmd_backup(args: argparse.Namespace) -> int:
    data_root = Path(args.data_root).resolve()
    if not (data_root / "persona").is_dir():
        log(f"ERROR: {data_root}/persona が見つからない（--data-root を確認）")
        return 1
    personas = args.persona or discover_personas(data_root)
    if not personas:
        log(f"ERROR: {data_root}/persona/*/memory.sqlite が無い（バックアップ対象なし）")
        return 1

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = Path(args.out).resolve() / f"nous-backup-{stamp}"
    if dest.exists():
        log(f"ERROR: {dest} は既に存在する")
        return 1
    dest.mkdir(parents=True)

    manifest: dict[str, Any] = {
        "format": FORMAT_BACKUP,
        "created_at": iso_now(),
        "data_root": str(data_root),
        "personas": personas,
        "contains_secrets": not args.no_config,
        "sqlite": {},
        "wiki": {},
        "config": None,
        "qdrant": {"available": False},
        "excluded": EXCLUDED,
    }

    log(f"[1/4] SQLite: {', '.join(personas)}")
    for persona in personas:
        pdir = data_root / "persona" / persona
        for db in sorted(pdir.glob("*.sqlite")):
            rel = f"{persona}/{db.name}"
            info = backup_sqlite(db, dest / "sqlite" / rel)
            manifest["sqlite"][rel] = info
            log(f"  sqlite: {rel} ({info['bytes']} bytes, integrity={info['integrity']})")

    log("[2/4] wiki")
    for persona in personas:
        info = copy_wiki(data_root / "persona" / persona / "wiki", dest / "wiki" / persona)
        manifest["wiki"][persona] = info
        log(f"  wiki: {persona} ({info['pages']} pages, {len(info['files'])} files)")

    log("[3/4] config")
    if not args.no_config:
        overrides = data_root / "config" / "config_overrides.json"
        if overrides.is_file():
            target = dest / "config" / "config_overrides.json"
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(overrides, target)
            manifest["config"] = {"file": "config/config_overrides.json", "sha256": sha256_file(target)}
            log("  config: config_overrides.json（API キーを含む。--no-config で除外できる）")
        else:
            log("  config: config_overrides.json なし（既定値で動作）")

    log("[4/4] Qdrant")
    base = qdrant_url(args.qdrant_url)
    key = qdrant_api_key(args.qdrant_api_key)
    if args.no_qdrant:
        log("  skip (--no-qdrant)")
        manifest["qdrant"] = {"available": False, "skipped": True}
    else:
        try:
            manifest["qdrant"] = snapshot_qdrant(base, key, personas, dest / "qdrant")
        except (urllib.error.URLError, TimeoutError, OSError, KeyError) as e:
            # ベクトルは wiki/SQLite から再構築できる派生物。バックアップ自体は続行する。
            manifest["qdrant"] = {"available": False, "url": base, "error": f"{type(e).__name__}: {e}"}
            log(f"  WARNING: Qdrant snapshot を取得できず（{e}）。wiki/SQLite のみのバックアップになる")

    write_json(dest / "manifest.json", manifest)
    ok = _verify_dir(dest, manifest)
    log(f"\n完了: {dest}  ({sum(f.stat().st_size for f in dest.rglob('*') if f.is_file())} bytes)")
    if not ok:
        return 1
    if not manifest["qdrant"].get("available") and not args.no_qdrant:
        return 0 if args.allow_partial else 2
    return 0


# ----------------------------------------------------------------------
# verify
# ----------------------------------------------------------------------


def _verify_dir(backup: Path, manifest: dict[str, Any]) -> bool:
    problems: list[str] = []
    for rel, info in manifest.get("sqlite", {}).items():
        path = backup / "sqlite" / rel
        if not path.is_file():
            problems.append(f"missing: sqlite/{rel}")
            continue
        if sha256_file(path) != info["sha256"]:
            problems.append(f"sha256 mismatch: sqlite/{rel}")
        integrity = sqlite_integrity(path)
        if integrity != "ok":
            problems.append(f"integrity: sqlite/{rel} -> {integrity}")
    for persona, info in manifest.get("wiki", {}).items():
        for rel, digest in info.get("files", {}).items():
            path = backup / "wiki" / persona / rel
            if not path.is_file():
                problems.append(f"missing: wiki/{persona}/{rel}")
            elif sha256_file(path) != digest:
                problems.append(f"sha256 mismatch: wiki/{persona}/{rel}")
    if manifest.get("config"):
        rel = manifest["config"]["file"]
        path = backup / rel
        if not path.is_file() or sha256_file(path) != manifest["config"]["sha256"]:
            problems.append(f"config: {rel} が欠落または破損")
    for info in manifest.get("qdrant", {}).get("collections", {}).values():
        path = backup / info["file"]
        if not path.is_file():
            problems.append(f"missing: {info['file']}")
        elif sha256_file(path) != info["sha256"]:
            problems.append(f"sha256 mismatch: {info['file']}")

    if problems:
        for p in problems:
            log(f"  NG: {p}")
        return False
    log("  OK: manifest のハッシュ・SQLite integrity_check すべて一致")
    return True


def cmd_verify(args: argparse.Namespace) -> int:
    backup = Path(args.backup).resolve()
    manifest = load_manifest(backup / "manifest.json")
    log(f"verify: {backup}")
    log(f"  created_at={manifest['created_at']} personas={','.join(manifest['personas'])}")
    q = manifest.get("qdrant", {})
    log(f"  qdrant={'included' if q.get('available') else 'excluded'}")
    return 0 if _verify_dir(backup, manifest) else 1


# ----------------------------------------------------------------------
# restore
# ----------------------------------------------------------------------


def _move_aside(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.move(str(src), str(dst))
    except OSError as e:
        _die(f"退避に失敗（復元中止。元データは未変更） {src} -> {dst}: {e}")


def cmd_restore(args: argparse.Namespace) -> int:
    backup = Path(args.backup).resolve()
    data_root = Path(args.data_root).resolve()
    manifest = load_manifest(backup / "manifest.json")
    if not _verify_dir(backup, manifest):
        if not args.force:
            log("ERROR: バックアップが検証を通らない。--force で強行しない限り復元しない")
            return 1
        log("WARNING: 検証 NG のまま復元する（--force）")

    personas = [p for p in manifest["personas"] if not args.persona or p in args.persona]
    if not personas:
        log("ERROR: 復元対象のペルソナが無い")
        return 1

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    conflicts = [
        target
        for persona in personas
        for target in (
            [
                data_root / "persona" / persona / rel.split("/", 1)[1]
                for rel in manifest["sqlite"]
                if rel.startswith(persona + "/")
            ]
            + ([data_root / "persona" / persona / "wiki"] if manifest["wiki"].get(persona) else [])
        )
        if target.exists()
    ]
    if conflicts and not args.force:
        for path in conflicts:
            log(f"  exists: {path}")
        log("ERROR: 復元先に既存データがある。--force を付けると `_pre_restore_<ts>` へ退避してから上書きする")
        return 1

    for persona in personas:
        pdir = data_root / "persona" / persona
        safety = pdir / f"_pre_restore_{stamp}"
        for rel in [r for r in manifest["sqlite"] if r.startswith(persona + "/")]:
            name = rel.split("/", 1)[1]
            for suffix in ("", "-wal", "-shm", "-journal"):
                current = pdir / (name + suffix)
                if current.exists():
                    _move_aside(current, safety / (name + suffix))
            (pdir / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(backup / "sqlite" / rel, pdir / name)
            log(f"  restored: persona/{persona}/{name}")
        wiki_info = manifest["wiki"].get(persona)
        if wiki_info:
            target = pdir / "wiki"
            if target.exists():
                _move_aside(target, safety / "wiki")
            shutil.copytree(backup / "wiki" / persona, target)
            _clean_stale_tmp(target)
            log(f"  restored: persona/{persona}/wiki ({wiki_info['pages']} pages)")

    if args.with_config and manifest.get("config"):
        target = data_root / "config" / "config_overrides.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            shutil.copy2(target, target.with_name(f"config_overrides.json.pre_restore_{stamp}"))
        shutil.copy2(backup / manifest["config"]["file"], target)
        log("  restored: config/config_overrides.json")

    if args.with_qdrant:
        base = args.qdrant_url or manifest["qdrant"].get("url") or qdrant_url(None)
        key = qdrant_api_key(args.qdrant_api_key)
        for name, info in manifest["qdrant"].get("collections", {}).items():
            if args.persona and not any(name.endswith("_" + p) for p in args.persona):
                continue
            try:
                restore_qdrant_snapshot(base, key, name, backup / info["file"])
                log(f"  restored: qdrant {name}")
            except Exception as e:  # noqa: BLE001 - 失敗してもファイル層の復元は確定済み
                log(f"  WARNING: qdrant {name} の復元に失敗: {e}")
                return 1
    else:
        log("  qdrant: skip（--with-qdrant で snapshot を戻す。省略時は起動後に再インデックスが必要）")

    log(f"\n完了。nous を再起動し /health と wiki 一覧を確認する。退避先: persona/*/_pre_restore_{stamp}")
    return 0


# ----------------------------------------------------------------------
# portable export
# ----------------------------------------------------------------------


def _nous_import_allowed() -> None:
    root = Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))


def export_memories_jsonl(data_root: Path, persona: str, target: Path) -> dict[str, Any]:
    """既存の JSONLExporter をそのまま使う（表の一覧を二重管理しない）。"""
    _nous_import_allowed()
    from nous.infrastructure.sqlite.connection import SQLiteConnection
    from nous.migration.exporters.jsonl_exporter import JSONLExporter

    conn = SQLiteConnection(str(data_root / "persona"), persona)
    try:
        result = JSONLExporter().export_persona(conn, persona, str(target))
    finally:
        conn.close()
    if not result.is_ok:
        raise RuntimeError(f"JSONL export failed: {result.error}")
    try:
        with open(target, encoding="utf-8") as f:
            records = sum(1 for line in f if line.strip())
    except OSError as e:
        _die(f"JSONL を読めない {target}: {e}")
    return {"records": records, "sha256": sha256_file(target)}


def _embedding_info(data_root: Path) -> dict[str, Any] | None:
    """再インデックス時に必要な埋め込みの同一性（モデル/次元）。"""
    try:
        _nous_import_allowed()
        from nous.config.settings import Settings

        cfg = Settings().embedding
        return {"model": cfg.model, "dimensions": cfg.dimensions}
    except Exception as e:  # noqa: BLE001 - 情報が取れなくてもエクスポートは続行
        log(f"  WARNING: embedding 設定を読めず（{e}）。manifest の embedding は null")
        return None


def cmd_export(args: argparse.Namespace) -> int:
    data_root = Path(args.data_root).resolve()
    personas = args.persona or discover_personas(data_root)
    if not personas:
        log("ERROR: 対象ペルソナなし")
        return 1
    out = Path(args.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")

    manifest: dict[str, Any] = {
        "format": FORMAT_PORTABLE,
        "created_at": iso_now(),
        "source_data_root": str(data_root),
        "policy": "wiki/*.md が正本。memories/*.jsonl は未編纂の生記憶。ベクトルは含めない（派生物）。",
        "embedding": _embedding_info(data_root),
        "personas": {},
        "contains_secrets": False,
    }
    tmp_dir = Path(os.environ.get("TMPDIR") or tempfile.gettempdir()) / f"nous-portable-{uuid.uuid4().hex[:8]}"
    tmp_dir.mkdir(parents=True)
    try:
        for persona in personas:
            wiki_rel = f"wiki/{persona}"
            info = copy_wiki(data_root / "persona" / persona / "wiki", tmp_dir / wiki_rel)
            memories = tmp_dir / f"memories/{persona}.jsonl"
            memories.parent.mkdir(parents=True, exist_ok=True)
            exp = export_memories_jsonl(data_root, persona, memories)
            manifest["personas"][persona] = {
                "wiki_pages": info["pages"],
                "wiki_files": len(info["files"]),
                "memories": exp["records"],
                "memories_sha256": exp["sha256"],
            }
            log(f"  {persona}: wiki {info['pages']} pages / memories {exp['records']} records")

        overrides = data_root / "config" / "config_overrides.json"
        if overrides.is_file():
            try:
                payload = json.loads(overrides.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                payload = {"unparsed": overrides.read_text(encoding="utf-8", errors="replace")}
            write_json(tmp_dir / "config" / "config_overrides.redacted.json", redact(payload))
            log("  config: config_overrides.redacted.json（機密値は伏字）")

        write_json(tmp_dir / "manifest.json", manifest)
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
            for path in sorted(tmp_dir.rglob("*")):
                if path.is_file():
                    zf.write(path, path.relative_to(tmp_dir).as_posix())
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    log(f"\n完了: {out} ({out.stat().st_size} bytes, stamp={stamp})")
    return 0


# ----------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="backup_restore", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    b = sub.add_parser("backup", help="整合バックアップ（SQLite + wiki + config + Qdrant snapshot）")
    b.add_argument("--data-root", default="./data")
    b.add_argument("--out", default="./backups")
    b.add_argument("--persona", action="append", help="対象ペルソナ（複数可。既定は memory.sqlite を持つ全員）")
    b.add_argument("--qdrant-url", default=None, help="既定は NOUS_QDRANT__URL か http://localhost:6333")
    b.add_argument("--qdrant-api-key", default=None)
    b.add_argument("--no-qdrant", action="store_true", help="Qdrant snapshot を取らない")
    b.add_argument("--no-config", action="store_true", help="config_overrides.json（API キー含む）を含めない")
    b.add_argument("--allow-partial", action="store_true", help="Qdrant 抜きでも終了コード 0（既定は 2）")
    b.set_defaults(func=cmd_backup)

    v = sub.add_parser("verify", help="manifest のハッシュと SQLite integrity_check を再検証")
    v.add_argument("--backup", required=True)
    v.set_defaults(func=cmd_verify)

    r = sub.add_parser("restore", help="バックアップから復元（既存データは退避してから置換）")
    r.add_argument("--backup", required=True)
    r.add_argument("--data-root", default="./data")
    r.add_argument("--persona", action="append")
    r.add_argument("--with-qdrant", action="store_true", help="snapshot を Qdrant へ戻す（qdrant-client 必須）")
    r.add_argument("--with-config", action="store_true", help="config_overrides.json も戻す")
    r.add_argument("--qdrant-url", default=None)
    r.add_argument("--qdrant-api-key", default=None)
    r.add_argument("--force", action="store_true", help="既存データを _pre_restore_<ts> へ退避して上書き")
    r.set_defaults(func=cmd_restore)

    e = sub.add_parser("export", help="ポータブルエクスポート（wiki md + memories JSONL + 伏字 config）")
    e.add_argument("--data-root", default="./data")
    e.add_argument("--out", default="./nous-portable.zip")
    e.add_argument("--persona", action="append")
    e.set_defaults(func=cmd_export)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    started = time.monotonic()
    code = args.func(args)
    log(f"[{args.command}] exit={code} ({time.monotonic() - started:.1f}s)")
    return code


if __name__ == "__main__":
    sys.exit(main())
