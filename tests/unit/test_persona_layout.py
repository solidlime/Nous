"""persona_layout: 旧レイアウト → 新レイアウトの移行。"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

from nous.infrastructure.persona_layout import migrate_persona_layout


def _w(path: Path, text: str = "x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_moves_db_wal_and_media(tmp_path: Path) -> None:
    data = tmp_path / "data"
    p = data / "persona" / "herta"
    _w(p / "memory.sqlite")
    _w(p / "memory.sqlite-wal")
    _w(p / "inventory.sqlite")
    _w(p / "images" / "a.png")
    _w(p / "tts_cache" / "b.wav")
    _w(p / "avatar" / "c.vrm")
    _w(p / "config.json", "{}")  # 対象外は動かさない

    moved = migrate_persona_layout(data)

    assert (p / "db" / "memory.sqlite").is_file()
    assert (p / "db" / "memory.sqlite-wal").is_file()
    assert (p / "db" / "inventory.sqlite").is_file()
    assert (p / "media" / "images" / "a.png").is_file()
    assert (p / "media" / "tts_cache" / "b.wav").is_file()
    assert (p / "media" / "avatar" / "c.vrm").is_file()
    assert (p / "config.json").is_file()
    assert moved


def test_moves_legacy_global_uploads(tmp_path: Path) -> None:
    data = tmp_path / "data"
    _w(data / "persona" / "herta" / "config.json", "{}")
    _w(data / "uploads" / "herta" / "note.txt", "hi")

    migrate_persona_layout(data)

    assert (data / "persona" / "herta" / "uploads" / "note.txt").read_text() == "hi"


def test_is_idempotent(tmp_path: Path) -> None:
    data = tmp_path / "data"
    p = data / "persona" / "herta"
    _w(p / "memory.sqlite")

    assert migrate_persona_layout(data)
    assert migrate_persona_layout(data) == []


def test_keeps_both_when_target_exists(tmp_path: Path) -> None:
    """新旧どちらにもあるときは上書きしない（片方のデータが消えるため）。"""
    data = tmp_path / "data"
    p = data / "persona" / "herta"
    _w(p / "memory.sqlite", "old")
    _w(p / "db" / "memory.sqlite", "new")

    moved = migrate_persona_layout(data)

    assert (p / "memory.sqlite").read_text() == "old"
    assert (p / "db" / "memory.sqlite").read_text() == "new"
    assert moved == []


def test_named_db_becomes_memory_sqlite(tmp_path: Path) -> None:
    """旧レイアウトの <persona>.db は db/memory.sqlite へ改名する。

    置き場所を変えるだけではアプリ（db/memory.sqlite を開く）に読まれないため。
    """
    data = tmp_path / "data"
    p = data / "persona" / "herta"
    _w(p / "herta.db", "body")
    _w(p / "herta.db-wal")

    migrate_persona_layout(data)

    assert (p / "db" / "memory.sqlite").read_text() == "body"
    assert (p / "db" / "memory.sqlite-wal").is_file()
    assert not (p / "herta.db").exists()


def test_named_db_does_not_clobber_existing_memory_sqlite(tmp_path: Path) -> None:
    data = tmp_path / "data"
    p = data / "persona" / "herta"
    _w(p / "herta.db", "old")
    _w(p / "db" / "memory.sqlite", "new")

    migrate_persona_layout(data)

    assert (p / "db" / "memory.sqlite").read_text() == "new"
    assert (p / "herta.db").read_text() == "old"  # 残す（どちらが正か機械では決められない）


def test_leftovers_are_quarantined_not_deleted(tmp_path: Path) -> None:
    """config.json.bak-* と wiki_cleanup_*.json は _legacy/ へ退ける。消さない。"""
    data = tmp_path / "data"
    p = data / "persona" / "herta"
    _w(p / "config.json", "{}")
    _w(p / "config.json.bak-sandbox", '{"old":1}')
    _w(p / "wiki_cleanup_20261108.json", "[]")

    moved = migrate_persona_layout(data)

    assert (p / "config.json").is_file()  # 現役の設定は動かさない
    assert (p / "_legacy" / "config.json.bak-sandbox").read_text() == '{"old":1}'
    assert (p / "_legacy" / "wiki_cleanup_20261108.json").is_file()
    assert moved


def test_quarantine_is_idempotent(tmp_path: Path) -> None:
    data = tmp_path / "data"
    p = data / "persona" / "herta"
    _w(p / "config.json.bak-sandbox", "x")

    assert migrate_persona_layout(data)
    assert migrate_persona_layout(data) == []


def test_each_persona_is_migrated(tmp_path: Path) -> None:
    """他ペルソナも同じ規則で移る（1つだけ特別扱いしない）。"""
    data = tmp_path / "data"
    for name in ("herta", "raurau"):
        _w(data / "persona" / name / "memory.sqlite")
        _w(data / "persona" / name / "images" / "a.png")

    moved = migrate_persona_layout(data)

    for name in ("herta", "raurau"):
        p = data / "persona" / name
        assert (p / "db" / "memory.sqlite").is_file()
        assert (p / "media" / "images" / "a.png").is_file()
    assert len(moved) == 4
