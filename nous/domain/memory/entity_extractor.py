"""Regex-based lightweight entity extraction. No LLM required."""

from __future__ import annotations

import re


class SimpleEntityExtractor:
    """Extract entity candidates from text using regular expressions.

    Designed for Japanese + mixed-language text.  Returns a de-duplicated
    list of ``(entity_name, entity_type)`` tuples.
    """

    # Katakana sequences (≥2 chars) — likely person / thing names.
    # Type is unknowable from surface form alone, so such candidates are
    # stored as ``entity`` (untyped), never asserted as ``person``.
    KATAKANA_NAME = re.compile(r"[\u30A0-\u30FF]{2,}")

    # Place suffixes (CJK / Katakana prefix + known suffix)
    PLACE_SUFFIX = re.compile(
        r"[\u4e00-\u9fff\u30A0-\u30FF]{1,}"
        r"(?:駅|公園|ビル|タワー|城|寺|神社|大学|学校|病院|空港|港|山|川|湖|海|島|橋|通り|広場)"
    )

    # English proper nouns: one or more consecutive Title-case words.
    # e.g. "John", "John Smith", "New York"
    ENGLISH_PROPER = re.compile(r"\b([A-Z][a-z]{1,}(?:\s+[A-Z][a-z]{1,})*)\b")

    # Japanese names with honorifics (漢字2-4文字 + 敬称)
    JAPANESE_NAME = re.compile(r"[一-龯]{2,4}(?:さん|くん|ちゃん|氏|様|先生)")
    # Suffix pattern for stripping honorifics
    _HONORIFIC_SUFFIX = re.compile(r"(?:さん|くん|ちゃん|氏|様|先生)$")

    # @mention: @username (ASCII + hiragana/katakana/kanji)
    MENTION = re.compile(r"@[\w\u3040-\u30FF\u4e00-\u9fff]{1,50}")

    # Common katakana stopwords to exclude
    _STOPWORDS: set[str] = frozenset(
        {
            "メモリ",
            "コンテキスト",
            "エラー",
            "テスト",
            "データ",
            "ステータス",
            "タグ",
            "リスト",
            "ブロック",
            "アイテム",
            "カテゴリ",
            "システム",
            "サーバー",
            "クライアント",
            "コンテンツ",
            "メタデータ",
            "パラメータ",
        }
    )

    # English words that look like proper nouns but are common words / pronouns
    _ENGLISH_STOPWORDS: frozenset[str] = frozenset(
        {
            "The",
            "A",
            "An",
            "Is",
            "Are",
            "Was",
            "Were",
            "Be",
            "Been",
            "I",
            "My",
            "We",
            "You",
            "It",
            "In",
            "On",
            "At",
            "To",
            "For",
            "With",
            "From",
            "By",
            "Of",
            "And",
            "Or",
            "But",
            "So",
            "As",
            "He",
            "She",
            "They",
            "His",
            "Her",
            "Their",
            "This",
            "That",
            "When",
            "Where",
            "How",
            "What",
            "Who",
            "Which",
        }
    )

    def extract(self, text: str) -> list[tuple[str, str]]:
        """Return ``[(entity_name, entity_type), ...]`` from *text*.

        Entity types: ``person``, ``place``, ``entity`` (untyped candidate).
        """
        if not text:
            return []

        entities: list[tuple[str, str]] = []

        # 1. Places first (suffix match has higher precision)
        place_texts: set[str] = set()
        for match in self.PLACE_SUFFIX.finditer(text):
            name = match.group()
            place_texts.add(name)
            entities.append((name, "place"))

        # 2. Katakana names (person OR thing — surface form can't tell them
        #    apart, so keep the type unclassified as "entity")
        for match in self.KATAKANA_NAME.finditer(text):
            name = match.group()
            if name not in place_texts and name not in self._STOPWORDS and len(name) >= 2:
                entities.append((name, "entity"))

        # 3. Japanese names with honorifics (敬称付き漢字人名)
        for match in self.JAPANESE_NAME.finditer(text):
            raw = match.group()
            base = self._HONORIFIC_SUFFIX.sub("", raw)
            if base and len(base) >= 2:
                entities.append((base, "person"))

        # 4. English proper nouns (consecutive Title-case words)
        for match in self.ENGLISH_PROPER.finditer(text):
            name = match.group()
            if name not in self._ENGLISH_STOPWORDS and len(name) >= 2:
                entities.append((name, "person"))

        # 5. @mentions
        for match in self.MENTION.finditer(text):
            name = match.group()[1:]  # strip leading '@'
            if name:
                entities.append((name, "person"))

        # De-duplicate while preserving first occurrence order
        seen: set[tuple[str, str]] = set()
        unique: list[tuple[str, str]] = []
        for pair in entities:
            if pair not in seen:
                seen.add(pair)
                unique.append(pair)
        return unique
