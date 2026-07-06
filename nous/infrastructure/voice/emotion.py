from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nous.domain.persona.entities import PersonaState

# ──────────────────────────────────────────────
# 感情→絵文字マッピング
# ──────────────────────────────────────────────
EMOTION_EMOJI: dict[str, str] = {
    "neutral": "",
    "joy": "😊",
    "sadness": "😢",
    "anger": "😠",
    "fear": "😨",
    "surprise": "😲",
    "disgust": "🤢",
    "excitement": "🤩",
    "love": "😍",
    "curiosity": "🤔",
    "anticipation": "😏",
}

# 感情→日本語キャプション
_EMOTION_CAPTIONS: dict[str, str] = {
    "neutral": "無表情で",
    "joy": "嬉しそうに",
    "sadness": "悲しそうに",
    "anger": "怒ったように",
    "fear": "怯えたように",
    "surprise": "驚いたように",
    "disgust": "嫌そうに",
    "excitement": "興奮したように",
    "love": "愛おしそうに",
    "curiosity": "興味深そうに",
    "anticipation": "期待に満ちて",
}


def build_caption(persona: PersonaState) -> str:
    """感情 + 口調 + コンテキストから自然言語のcaptionを生成する。

    フィールドが存在するものを柔軟に組み合わせる。
    - emotion → "嬉しそうに"
    - speech_style → "元気な口調で"
    - context_note → "（将来対応）" など
    """
    parts: list[str] = []

    # 1. 感情
    caption = _EMOTION_CAPTIONS.get(persona.emotion)
    if caption:
        parts.append(caption)

    # 2. 口調 (speech_style)
    if persona.speech_style:
        style = persona.speech_style.strip()
        # "口調" が含まれていなければ "〜な口調で" を補完
        if "口調" not in style:
            parts.append(f"{style}口調で")
        else:
            parts.append(style)

    # 3. コンテキスト (context_note — 将来 PersonaState に追加される可能性がある)
    context_note = getattr(persona, "context_note", None)
    if context_note:
        parts.append(context_note)

    return "、".join(parts) if parts else "普通に"
