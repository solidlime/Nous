"""nous/application/chat/expression.py

表情ライブラリ: persona 画像ディレクトリの expr_<emotion>.png を管理する。
状態の正典はファイルシステム。LLM 関知なしの決定論的関数のみ。
"""

from __future__ import annotations

import re
from pathlib import Path

from nous.config.settings import get_settings

EXPRESSION_PREFIX = "expr_"
_EMOTION_PATTERN = re.compile(r"^[a-z_]+$")


def is_valid_emotion_label(emotion: str) -> bool:
    """ファイル名に安全な感情ラベルか（LLM 出力を信頼しない）。"""
    return bool(emotion) and _EMOTION_PATTERN.fullmatch(emotion) is not None


def expressions_dir(persona: str) -> Path:
    return Path(get_settings().data_root) / "persona" / persona / "images"


def expression_image_path(persona: str, emotion: str) -> Path:
    return expressions_dir(persona) / f"{EXPRESSION_PREFIX}{emotion}.png"


def resolve_expression_url(persona: str, emotion: str) -> str | None:
    """感情に対応する表情画像の URL を返す。無ければ None。"""
    if not is_valid_emotion_label(emotion):
        return None
    path = expression_image_path(persona, emotion)
    if path.is_file():
        return f"/api/chat/{persona}/persona/images/{path.name}"
    return None


def save_expression_image(persona: str, emotion: str, png_bytes: bytes) -> str:
    """表情画像を保存し URL を返す。"""
    if not is_valid_emotion_label(emotion):
        msg = f"Invalid emotion label: {emotion!r}"
        raise ValueError(msg)
    path = expression_image_path(persona, emotion)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(png_bytes)
    return f"/api/chat/{persona}/persona/images/{path.name}"
