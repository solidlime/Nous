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
