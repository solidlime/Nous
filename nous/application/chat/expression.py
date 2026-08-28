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


# 感情 → 表情プロンプトの差分指示。未知ラベルはフォールバック形式。
# ラベル集合自体は ALLOWED_EMOTIONS（nous/domain/memory/value_objects.py）を正典とする。
EMOTION_EXPRESSION_HINTS: dict[str, str] = {
    "joy": "bright joyful smile, sparkling eyes",
    "sad": "downcast eyes, sorrowful expression",
    "angry": "pouting, irritated expression",
    "surprise": "wide eyes, surprised open mouth",
    "fear": "trembling, anxious expression",
    "disgust": "scowling, displeased expression",
    "neutral": "calm neutral expression",
}


def _expression_prompt(config, emotion: str) -> str:
    """persona の self-portrait プロンプトをベースに感情差分を足す。"""
    self_prompt = getattr(config, "image_gen_self_portrait_prompt", "") or ""
    hint = EMOTION_EXPRESSION_HINTS.get(emotion, f"{emotion} facial expression")
    return f"{self_prompt}, portrait, upper body, {hint}".strip(", ")


def _build_provider(config, size: str):
    """ChatConfig から ComfyUIProvider を構築する（builtin.py の image_generate と同型）。"""
    from nous.infrastructure.image_gen.comfyui import ComfyUIProvider

    return ComfyUIProvider(
        api_url=getattr(config, "image_gen_comfyui_url", "") or "http://localhost:8188",
        width=768,
        height=768,
        workflow_template=getattr(config, "image_gen_comfyui_workflow_template", ""),
        workflow_source=getattr(config, "image_gen_comfyui_workflow_source", "local"),
        workflow_name=getattr(config, "image_gen_comfyui_workflow_name", ""),
        timeout_seconds=getattr(config, "image_gen_comfyui_timeout_seconds", 180),
    )


async def generate_expression_image(config, persona: str, emotion: str) -> str | None:
    """ComfyUI で表情差分を 1 枚生成してライブラリに保存する。失敗時は None。"""
    import base64
    import logging

    if not is_valid_emotion_label(emotion):
        return None
    if not getattr(config, "image_gen_enabled", False):
        logging.getLogger(__name__).info("Expression generation skipped: image_gen disabled (persona=%s)", persona)
        return None
    try:
        provider = _build_provider(config, "768x768")
        generated = await provider.generate(
            prompt=_expression_prompt(config, emotion),
            size="768x768",
            n=1,
            negative_prompt=getattr(config, "image_gen_negative_prompt", "") or "",
        )
        for img in generated:
            if not getattr(img, "display", True):
                continue
            return save_expression_image(persona, emotion, base64.b64decode(img.base64))
        return None
    except Exception as e:
        logging.getLogger(__name__).warning(
            "Expression generation failed (persona=%s emotion=%s): %s", persona, emotion, e
        )
        return None
