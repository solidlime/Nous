"""Sudachi-based tokenization for the FTS5 index.

The FTS5 table uses the bundled ``unicode61`` tokenizer, which treats a whole
run of CJK characters as ONE token. Morpheme-level Japanese queries (e.g.
``量子テレポーテーション`` against content ``…は量子テレポーテーションの…``)
therefore never match the raw index. Fix: pre-segment BOTH sides — index
content and queries — into Sudachi surface tokens joined by spaces, so
``unicode61`` sees one token per morpheme.

If sudachipy / the dictionary is unavailable, falls back to the raw text
(degraded to the previous behavior, never crashes writes or searches).
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

_tokenizer = None
_load_failed = False

# Lazy import to avoid a hard dependency at module import time.
SUDACHI_DICT_VERSION = "20260428"
SUDACHI_DICT_TYPE = "core"
SUDACHI_DICT_FILENAME = f"system_{SUDACHI_DICT_TYPE}.dic"


def _get_dict_path() -> str:
    data_root = os.environ.get("NOUS_DATA_ROOT", "./data")
    return os.path.join(data_root, "sudachi", SUDACHI_DICT_FILENAME)


def _get_tokenizer():
    """Lazily build and cache the Sudachi tokenizer (None on failure)."""
    global _tokenizer, _load_failed
    if _tokenizer is not None or _load_failed:
        return _tokenizer
    try:
        from sudachipy import Dictionary  # noqa: PLC0415 — lazy import

        dict_path = _get_dict_path()
        if not os.path.exists(dict_path):
            logger.warning("Sudachi dictionary not found at %s; FTS keeps raw text", dict_path)
            _load_failed = True
            return None
        _tokenizer = Dictionary(dict=dict_path).create()
    except Exception as e:  # noqa: BLE001 — degrade to raw text, never crash callers
        _load_failed = True
        logger.warning("sudachipy unavailable (%s); FTS keeps raw text", e)
    return _tokenizer


def tokenize_for_fts(text: str) -> str:
    """Segment *text* into Sudachi surface tokens joined by single spaces.

    Returns the input unchanged when the tokenizer is unavailable or yields
    nothing usable.
    """
    tok = _get_tokenizer()
    if tok is None:
        return text
    try:
        tokens = [m.surface() for m in tok.tokenize(text) if m.surface().strip()]
    except Exception:  # noqa: BLE001 — per-call safety net
        return text
    return " ".join(tokens) if tokens else text
