"""プロフィール文書のトークン数推定（純関数・依存ゼロ）.

設計: 日次 curation / profile_update の上限ゲート（既定 3000 token）で使う。
`tiktoken` 等のトークナイザ同梱は却下済み（依存追加と CPU コストに見合わない、
上限判定は ±15% 精度で十分）。係数は実測で置き換えられるようモジュール定数に固定する。
"""

from __future__ import annotations

from math import ceil

# 実測（設計書 §7-1）後にこの 4 値だけ差し替えれば校正が済む形にする
TOKEN_WEIGHTS: dict[str, float] = {
    "cjk": 1.0,
    "ascii": 0.28,
    "other": 0.5,
    "safety": 1.05,
}

# me / user 各ブロックの上限（config で上書き可能 — settings 側の既定値と一致させる）
DEFAULT_PROFILE_MAX_TOKENS = 3000

# CJK・全角・ハングルのコードポイント範囲（BPE で概ね 1 文字 ≒ 1 トークン）
_CJK_RANGES: tuple[tuple[int, int], ...] = (
    (0x1100, 0x11FF),  # Hangul Jamo
    (0x2E80, 0x2EFF),  # CJK Radicals Supplement
    (0x3000, 0x303F),  # CJK Symbols and Punctuation
    (0x3040, 0x309F),  # Hiragana
    (0x30A0, 0x30FF),  # Katakana
    (0x3130, 0x318F),  # Hangul Compatibility Jamo
    (0x3400, 0x4DBF),  # CJK Extension A
    (0x4E00, 0x9FFF),  # CJK Unified Ideographs
    (0xA960, 0xA97F),  # Hangul Jamo Extended-A
    (0xAC00, 0xD7AF),  # Hangul Syllables
    (0xF900, 0xFAFF),  # CJK Compatibility Ideographs
    (0xFF00, 0xFFEF),  # Halfwidth and Fullwidth Forms
    (0x20000, 0x2FA1F),  # CJK Extension B and beyond
    (0x1F200, 0x1F2FF),  # Enclosed Ideographic Supplement
)


def _weight(char: str) -> float:
    code = ord(char)
    if code < 0x80:
        return TOKEN_WEIGHTS["ascii"]
    if any(lo <= code <= hi for lo, hi in _CJK_RANGES):
        return TOKEN_WEIGHTS["cjk"]
    return TOKEN_WEIGHTS["other"]


def estimate_tokens(text: str) -> int:
    """``text`` の推定トークン数（切り上げ、空文字は 0）."""
    if not text:
        return 0
    raw = sum(_weight(c) for c in text)
    return ceil(raw * TOKEN_WEIGHTS["safety"])


def exceeds_profile_limit(text: str, max_tokens: int = DEFAULT_PROFILE_MAX_TOKENS) -> bool:
    """上限ゲート。``estimate_tokens(text) > max_tokens`` の糖衣."""
    return estimate_tokens(text) > max_tokens
