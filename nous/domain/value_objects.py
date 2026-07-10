"""Domain value objects for nous."""

from __future__ import annotations

_EMOTION_KEYWORD_MAP: dict[str, list[str]] = {
    "joy": [
        "joy",
        "happy",
        "happiness",
        "glad",
        "delighted",
        "pleased",
        "cheerful",
        "elated",
        "嬉しい",
        "幸せ",
        "喜び",
        "楽しい",
    ],
    "sadness": [
        "sad",
        "unhappy",
        "sorrow",
        "grief",
        "depressed",
        "down",
        "melancholy",
        "悲しい",
        "悲しみ",
        "憂鬱",
        "落ち込む",
    ],
    "anger": ["anger", "angry", "furious", "irritated", "annoyed", "rage", "mad", "怒り", "怒る", "イライラ", "腹立つ"],
    "fear": ["fear", "afraid", "scared", "terrified", "anxious", "dread", "nervous", "恐怖", "怖い", "不安", "恐れ"],
    "surprise": ["surprise", "surprised", "shocked", "astonished", "amazed", "unexpected", "驚き", "驚く", "びっくり"],
    "disgust": ["disgust", "disgusted", "repulsed", "revolted", "nauseated", "嫌悪", "嫌い", "不快", "気持ち悪い"],
    "love": ["love", "affection", "adore", "fond", "caring", "tender", "devotion", "愛", "愛情", "大好き", "好き"],
    "neutral": ["neutral", "okay", "fine", "normal", "calm", "平静", "普通", "落ち着く", "ニュートラル"],
    "anticipation": [
        "anticipation",
        "anticipate",
        "looking forward",
        "eager",
        "expect",
        "期待",
        "楽しみ",
        "待ちわびる",
    ],
    "trust": ["trust", "confident", "reliable", "faith", "believe", "信頼", "信じる", "安心", "頼もしい"],
    "anxiety": ["anxiety", "anxious", "worried", "worry", "apprehensive", "uneasy", "心配", "不安", "ドキドキ", "緊張"],
    "excitement": [
        "excitement",
        "excited",
        "thrilled",
        "enthusiastic",
        "pumped",
        "exhilarated",
        "興奮",
        "わくわく",
        "テンション",
    ],
    "frustration": [
        "frustration",
        "frustrated",
        "stuck",
        "unable",
        "フラストレーション",
        "もどかしい",
        "うまくいかない",
    ],
    "nostalgia": [
        "nostalgia",
        "nostalgic",
        "miss",
        "remember",
        "reminisce",
        "fond memory",
        "ノスタルジア",
        "懐かしい",
        "懐かしさ",
    ],
    "pride": ["pride", "proud", "accomplished", "achievement", "satisfied", "誇り", "誇らしい", "達成感", "自信"],
    "shame": ["shame", "ashamed", "embarrassed", "humiliated", "恥", "恥ずかしい", "みじめ"],
    "guilt": ["guilt", "guilty", "regret", "remorse", "apologetic", "罪悪感", "後悔", "申し訳ない"],
    "loneliness": ["loneliness", "lonely", "isolated", "alone", "孤独", "孤独感", "寂しい", "ひとり"],
    "contentment": ["contentment", "content", "at peace", "serene", "穏やか", "満足", "充実", "安らぎ"],
    "curiosity": [
        "curiosity",
        "curious",
        "interested",
        "wonder",
        "inquisitive",
        "好奇心",
        "興味",
        "気になる",
        "知りたい",
    ],
    "awe": ["awe", "awestruck", "reverence", "畏敬", "すごい", "圧倒される"],
    "relief": ["relief", "relieved", "unburdened", "安堵", "ほっとする", "安心した"],
    "envy": ["envy", "envious", "jealous", "jealousy", "妬み", "嫉妬", "羨ましい"],
    "gratitude": ["gratitude", "grateful", "thankful", "appreciative", "感謝", "ありがたい", "恩"],
    "contempt": ["contempt", "contemptuous", "scorn", "disdain", "軽蔑", "蔑み", "見下す"],
}


def normalize_emotion(text: str | None) -> str:
    """Normalize free-text emotion to one of the 22 canonical emotion labels.

    Returns 'neutral' for None, empty string, or unrecognized input.
    """
    if not text:
        return "neutral"

    lower = text.lower().strip()

    # Exact match first
    if lower in _EMOTION_KEYWORD_MAP:
        return lower

    # Keyword scan
    for label, keywords in _EMOTION_KEYWORD_MAP.items():
        for kw in keywords:
            if kw in lower:
                return label

    return "neutral"


# Canonical set of valid emotion labels (frozenset for fast O(1) membership checks)
_VALID_EMOTIONS: frozenset[str] = frozenset(_EMOTION_KEYWORD_MAP.keys())


# ──────────────────────────────────────────────
# 感情→絵文字マッピング（正規定義）
# ──────────────────────────────────────────────
EMOTION_EMOJI: dict[str, str] = {
    "neutral": "😐",
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
    "grief": "😥",
}


def normalize_importance(value: float | None) -> float:
    """Clamp importance to [0.0, 1.0] range. Returns 0.5 for None."""
    if value is None:
        return 0.5
    return max(0.0, min(1.0, value))


def importance_to_label(importance: float) -> str:
    """Convert float importance (0.0-1.0) to human-readable label.

    Thresholds:
        >= 0.9  → "critical"
        >= 0.7  → "high"
        >= 0.4  → "normal"
        <  0.4  → "low"
    """
    if importance >= 0.9:
        return "critical"
    elif importance >= 0.7:
        return "high"
    elif importance >= 0.4:
        return "normal"
    else:
        return "low"
