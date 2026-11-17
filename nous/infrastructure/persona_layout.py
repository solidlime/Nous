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

起動時（DB を開く前）に一度だけ走る。冪等。何も消さない：

- ``<p>.db``（旧命名の DB）は ``db/memory.sqlite`` へ改名して移す。
  ``db/memory.sqlite`` が既にある場合はどちらが正か決められないので触らない。
- ``config.json.bak*`` / ``wiki_cleanup_*.json`` は ``_legacy/`` へ退ける。
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

# 旧レイアウト由来の残骸。中身が読める保証がないので消さずに隔離する。
_LEGACY_GLOBS: tuple[str, ...] = ("config.json.bak*", "wiki_cleanup_*.json")
QUARANTINE_DIR = "_legacy"


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


def _quarantine_leftovers(persona_dir: Path, moved: list[str]) -> None:
    """旧レイアウトの残骸を ``_legacy/`` へ退ける（削除はしない）。

    ``config.json.bak-sandbox`` のようなバックアップや ``wiki_cleanup_*.json`` の
    レポートは、sandbox に見せる必要も DB の隣に置く必要も無い。
    """
    for pattern in _LEGACY_GLOBS:
        for src in sorted(persona_dir.glob(pattern)):
            if src.parent.name == QUARANTINE_DIR:
                continue
            _move(src, persona_dir / QUARANTINE_DIR / src.name, moved)


def _move_named_db(persona_dir: Path, moved: list[str]) -> None:
    """``<persona>.db`` を ``db/memory.sqlite`` へ改名して移す。

    旧レイアウトはペルソナ名の DB（``herta/herta.db``）を使っていた。アプリが開くのは
    ``db/memory.sqlite`` なので、置き場所を変えるだけでは読まれない。
    移し先に既に DB がある場合は手で比べてもらう（どちらが正かは機械では決められない）。
    """
    src = persona_dir / f"{persona_dir.name}.db"
    if src.exists():
        _move(src, persona_dir / "db" / "memory.sqlite", moved)
        for suffix in _WAL_SUFFIXES:
            wal = persona_dir / f"{persona_dir.name}.db{suffix}"
            if wal.exists():
                _move(wal, persona_dir / "db" / f"memory.sqlite{suffix}", moved)


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

        _move_named_db(persona_dir, moved)
        _quarantine_leftovers(persona_dir, moved)

    if moved:
        logger.info("persona layout: %d 件を移行した", len(moved))
        for line in moved:
            logger.info("  %s", line)
    return moved
