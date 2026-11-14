"""scripts/backup_restore.py のバックアップ→検証→復元とポータブルエクスポート。

ネットワーク（Qdrant）は使わない。整合性の担保はファイル層と SQLite の
backup API / integrity_check で検証する。
"""

from __future__ import annotations

import importlib.util
import json
import zipfile
from pathlib import Path

import pytest

from nous.infrastructure.sqlite.connection import SQLiteConnection
from nous.infrastructure.wiki.store import WikiStore

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_script():
    spec = importlib.util.spec_from_file_location("backup_restore", REPO_ROOT / "scripts" / "backup_restore.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def data_root(tmp_path) -> Path:
    root = tmp_path / "data"
    conn = SQLiteConnection(data_dir=str(root / "persona"), persona="herta")
    conn.initialize_schema()
    conn.get_memory_db().execute(
        "INSERT INTO memories (key, content, created_at, updated_at) VALUES (?, ?, ?, ?)",
        ("k1", "hello", "2026-01-01T00:00:00+09:00", "2026-01-01T00:00:00+09:00"),
    )
    conn.close()
    WikiStore(root, "herta").write_page("topics/nous", "Nous 概要", "本文")
    (root / "config").mkdir(parents=True, exist_ok=True)
    (root / "config" / "config_overrides.json").write_text(
        json.dumps({"general": {"api_key": "sk-secret", "log_level": "INFO"}}), encoding="utf-8"
    )
    return root


def test_backup_verify_restore_roundtrip(tmp_path, data_root):
    br = _load_script()
    out = tmp_path / "backups"
    assert br.main(["backup", "--data-root", str(data_root), "--out", str(out), "--no-qdrant"]) == 0
    backup = next(out.glob("nous-backup-*"))
    assert br.main(["verify", "--backup", str(backup)]) == 0

    manifest = json.loads((backup / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["sqlite"]["herta/memory.sqlite"]["rows"]["memories"] == 1
    assert manifest["sqlite"]["herta/memory.sqlite"]["integrity"] == "ok"
    assert manifest["wiki"]["herta"]["pages"] == 1
    assert manifest["contains_secrets"] is True

    # 改竄すると verify は落ちる（復元側も止まる）
    (backup / "wiki" / "herta" / "topics" / "nous.md").write_text("tampered", encoding="utf-8")
    assert br.main(["verify", "--backup", str(backup)]) == 1

    # 元の内容に戻して復元
    br_main_backup = backup
    assert br.main(["backup", "--data-root", str(data_root), "--out", str(tmp_path / "b2"), "--no-qdrant"]) == 0
    fresh = next((tmp_path / "b2").glob("nous-backup-*"))
    assert br_main_backup != fresh

    target = tmp_path / "restored"
    (target / "persona" / "herta").mkdir(parents=True)
    assert br.main(["restore", "--backup", str(fresh), "--data-root", str(target)]) == 0

    conn = SQLiteConnection(data_dir=str(target / "persona"), persona="herta")
    try:
        rows = conn.get_memory_db().execute("SELECT content FROM memories").fetchall()
    finally:
        conn.close()
    assert [r[0] for r in rows] == ["hello"]
    assert (target / "persona" / "herta" / "wiki" / "topics" / "nous.md").is_file()

    # 既存データがある状態の復元は --force 無しでは拒否し、--force では退避する
    assert br.main(["restore", "--backup", str(fresh), "--data-root", str(target)]) == 1
    assert br.main(["restore", "--backup", str(fresh), "--data-root", str(target), "--force"]) == 0
    assert list((target / "persona" / "herta").glob("_pre_restore_*/memory.sqlite"))


def test_portable_export_redacts_secrets(tmp_path, data_root):
    br = _load_script()
    out = tmp_path / "portable.zip"
    assert br.main(["export", "--data-root", str(data_root), "--out", str(out)]) == 0

    with zipfile.ZipFile(out) as zf:
        names = set(zf.namelist())
        manifest = json.loads(zf.read("manifest.json"))
        config = json.loads(zf.read("config/config_overrides.redacted.json"))

    assert manifest["format"] == "nous-portable/1"
    assert manifest["personas"]["herta"]["wiki_pages"] == 1
    assert manifest["personas"]["herta"]["memories"] == 1
    assert "wiki/herta/topics/nous.md" in names
    assert "memories/herta.jsonl" in names
    assert not any(n.startswith("qdrant/") for n in names)
    assert config["general"]["api_key"] == "***redacted***"
    assert config["general"]["log_level"] == "INFO"
