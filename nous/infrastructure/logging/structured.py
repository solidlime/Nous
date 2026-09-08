from __future__ import annotations

import logging
import sys


def setup_logging(level: str = "INFO") -> None:
    """Configure structured logging for the application."""
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stderr,
    )


def get_logger(name: str) -> logging.Logger:
    """Get a named logger — "nous." プレフィックスは常にちょうど1回付与する。

    呼び出し側が get_logger(__name__) のように完全修飾名（nous. 付き）を渡しても
    二重付与しない（旧挙動では nous.nous.application... になっていた）。
    """
    if name.startswith("nous."):
        name = name[len("nous.") :]
    return logging.getLogger(f"nous.{name}")
