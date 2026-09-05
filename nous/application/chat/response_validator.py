"""Rule-based response validator for persona-independent quality checks."""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

# AI self-identification patterns (common in LLM outputs that break persona immersion)
_AI_SELF_ID_PATTERNS: list[str] = [
    r"(?i)\bas an AI\b",
    r"(?i)\bas a language model\b",
    r"(?i)\bI'm an AI\b",
    r"(?i)\bI am an AI\b",
    r"(?i)\bI am not (a |)human\b",
]

# Repetition threshold: same sentence/phrase repeated N+ times
_REPETITION_THRESHOLD = 3
_REPETITION_MIN_LENGTH = 10  # chars, to avoid false positives on short words

# Garbled text ranges — matching context_loader.py _SUSPICIOUS_RANGES
# N'Ko, Mongolian, PUA, Surrogates — LLM BPE tokenizer artifacts
_GARBLED_RE = re.compile(
    "["
    "\u07c0-\u07ff"  # N'Ko
    "\u1800-\u18af"  # Mongolian
    "\ue000-\uf8ff"  # Private Use Area
    "\ud800-\udfff"  # Surrogates (lone surrogates)
    "]"
)


def validate_response(text: str) -> list[str]:
    """Validate a response text. Returns list of warning messages (empty = clean)."""
    if not text or not text.strip():
        return ["Response is empty or whitespace-only"]

    warnings: list[str] = []

    # 1. AI self-identification check
    for pattern in _AI_SELF_ID_PATTERNS:
        if re.search(pattern, text):
            warnings.append(f"AI self-identification detected: matched '{pattern}'")
            break  # one match is enough

    # 2. Excessive repetition check
    sentences = _split_sentences(text)
    if len(sentences) >= _REPETITION_THRESHOLD:
        seen: dict[str, int] = {}
        for s in sentences:
            s_stripped = s.strip()
            if len(s_stripped) >= _REPETITION_MIN_LENGTH:
                seen[s_stripped] = seen.get(s_stripped, 0) + 1
        for sentence, count in seen.items():
            if count >= _REPETITION_THRESHOLD:
                warnings.append(f"Phrase repeated {count} times: '{sentence[:80]}...'")
                break  # one example is enough

    # 3. Garbled text (BPE artifact) check
    garbled = _check_garbled_text(text)
    if garbled:
        warnings.append(garbled)

    # 4. Timestamp echo check
    timestamp_echo_patterns = [
        r"(\[?\d{4}[-/年]\d{1,2}[-/月]\d{1,2}[日\]]?\s*\d{1,2}:\d{2}(:\d{2})?\s*(JST|UTC[\+\-]\d{1,2})?)",
        r"([Nn]ow:\s*\d{4}-\d{2}-\d{2})",
        r"(現在時刻[は:：]\s*\d{4}年\d{1,2}月\d{1,2}日)",
        r"(Current time:?\s*\d{4}-\d{2}-\d{2})",
    ]
    for pattern in timestamp_echo_patterns:
        m = re.search(pattern, text)
        if m:
            warnings.append(f"Timestamp echo detected: {m.group(0)[:60]}")
            break

    # 5. XML tag leak check
    xml_tag_leak_patterns = [
        r"<time_context>",
        r"</time_context>",
        r"<time>",
        r"</time>",
        r"<retrieved_data>",
        r"</retrieved_data>",
        r"<current_state>",
        r"<related_memories>",
        r"<precedence>",
    ]
    for pattern in xml_tag_leak_patterns:
        if re.search(pattern, text):
            warnings.append(f"Internal XML tag leaked in response: {pattern}")
            break  # one match is enough

    return warnings


def _split_sentences(text: str) -> list[str]:
    """Split text into sentences by common delimiters."""
    return re.split(r"(?<=[。！？.!?])\s*", text)


def _check_garbled_text(text: str) -> str | None:
    """Check for BPE-tokenization garbage characters.

    Based on _sanitize_text() pattern from context_loader.py:81-101.
    Returns warning string or None.
    """
    garbled = _GARBLED_RE.findall(text)
    if garbled:
        ratio = len(garbled) / max(len(text), 1)
        if ratio > 0.05:
            return f"Garbled text detected ({len(garbled)} chars, {ratio:.1%}): ..."
    return None
