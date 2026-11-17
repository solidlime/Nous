"""ペルソナディレクトリの旧→新レイアウト移行。

新レイアウトは DB と生成物をサブディレクトリに分ける:

    persona/<p>/db/        memory.sqlite, inventory.sqlite
    persona/<p>/media/     images, tts_cache, avatar
    persona/<p>/wiki/
    persona/<p>/uploads/
    persona/<p>/workspace/

旧レイアウトはこれらが persona/<p>/ 直下に散らばり、uploads だけは
グローバルな {data_root}/uploads/<p>/ にあった。sandbox に見せる範囲を
絞る（db と config.json を見せない）ために分ける。

起動時（DB を開く前）に一度だけ走る。冪等。
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)

# 旧名 → 移動先サブディレクトリ。ディレクトリでもファイルでも同じ扱い。
_MOVES: tuple[tuple[str, str], ...] = (
    ("memory.sqlite", "db"),
    ("memory.db", "db"),
    ("nous.db", "db"),
    ("inventory.sqlite", "db"),
    ("images", "media"),
    ("tts_cache", "media"),
    ("avatar", "media"),
)

# SQLite の WAL / SHM は DB と同じ場所でないと開けないので、一緒に移す。
_WAL_SUFFIXES = ("-wal", "-shm")


def persona_db_dir(data_root: str | Path, persona: str) -> Path:
    """{data_root}/persona/{persona}/db"""
    return Path(data_root) / "persona" / persona / "db"


def persona_media_dir(data_root: str | Path, persona: str) -> Path:
    """{data_root}/persona/{persona}/media（images / tts_cache / avatar）"""
    return Path(data_root) / "persona" / persona / "media"


def persona_uploads_dir(data_root: str | Path, persona: str) -> Path:
    """{data_root}/persona/{persona}/uploads"""
    return Path(data_root) / "persona" / persona / "uploads"


def _move(src: Path, dst: Path, moved: list[str]) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        # 新旧どちらにもある＝前回が中途半端。上書きすると片方のデータが消える。
        logger.warning("persona layout: %s と %s が両方ある。手で片付けること", src, dst)
        return
    try:
        shutil.move(str(src), str(dst))
    except OSError:
        # 権限やクロスデバイスで失敗しても起動は続ける（旧パスを見れば動く）。
        logger.exception("persona layout: %s を %s に移せない", src, dst)
        return
    moved.append(f"{src} -> {dst}")


def migrate_persona_layout(data_root: Path) -> list[str]:
    """{data_root}/persona/<p>/ を新レイアウトへ移す。移したものの説明を返す。"""
    moved: list[str] = []
    persona_root = data_root / "persona"
    if not persona_root.is_dir():
        return moved

    for persona_dir in sorted(p for p in persona_root.iterdir() if p.is_dir()):
        for old_name, sub in _MOVES:
            src = persona_dir / old_name
            if not src.exists():
                continue
            _move(src, persona_dir / sub / old_name, moved)
            for suffix in _WAL_SUFFIXES:
                wal = persona_dir / f"{old_name}{suffix}"
                if wal.exists():
                    _move(wal, persona_dir / sub / f"{old_name}{suffix}", moved)

        # uploads だけはグローバル（{data_root}/uploads/<p>/）にあった。
        legacy_uploads = data_root / "uploads" / persona_dir.name
        if legacy_uploads.is_dir():
            _move(legacy_uploads, persona_dir / "uploads", moved)

    if moved:
        logger.info("persona layout: %d 件を移行した", len(moved))
        for line in moved:
            logger.info("  %s", line)
    return moved
