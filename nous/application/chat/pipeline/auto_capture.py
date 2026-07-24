"""Auto-capture: extract key information from session turns via heuristics.

Uses simple regex patterns (no LLM cost) to find decisions, preferences,
facts, problems, and commitments in the latest conversation exchange.
Created memories are tagged with 'auto_captured' + the category tag.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from nous.infrastructure.logging.structured import get_logger

if TYPE_CHECKING:
    from nous.application.use_cases import AppContext
    from nous.domain.chat_config import ChatConfig

logger = get_logger(__name__)

# ── Category patterns ──────────────────────────────────────────────
# Each entry: (compiled_regex, category_tag)
_CATEGORIES: list[tuple[re.Pattern, str]] = [
    # Decisions
    (re.compile(r"(ことにした|決めた|決定|will do|decided to|going to)"), "decision"),
    # Preferences
    (
        re.compile(r"(好き|好み|欲しい|の方がいい|prefer|like|want|would rather)"),
        "preference",
    ),
    # Facts learned
    (re.compile(r"(実は|実際は|覚えて|思い出した|remember that|fact:)"), "fact"),
    # Problems
    (
        re.compile(r"(問題|困った|難しい|課題|トラブル|problem|issue|difficult)"),
        "problem",
    ),
    # Commitments
    (
        re.compile(r"(約束|必ず|絶対|確実に|promise|commit to|will make sure)"),
        "commitment",
    ),
]

# Heuristic: minimum importance per category
_CATEGORY_IMPORTANCE: dict[str, float] = {
    "decision": 0.6,
    "preference": 0.4,
    "fact": 0.5,
    "problem": 0.6,
    "commitment": 0.7,
}


def _extract_sentence(text: str, match_start: int) -> str:
    """Extract the sentence surrounding a match from text.

    Finds the sentence boundaries (。.！!？?改行) around the match position.
    """
    # Find sentence start: after previous sentence delimiter or from beginning
    sent_start = 0
    for sep in ("。", ".", "！", "!", "？", "?", "\n"):
        idx = text.rfind(sep, 0, match_start)
        if idx != -1:
            sent_start = max(sent_start, idx + 1)
    # Backtrack whitespace
    while sent_start < len(text) and text[sent_start] in " \t\n\r":
        sent_start += 1

    # Find sentence end: next sentence delimiter
    sent_end = len(text)
    for sep in ("。", ".", "！", "!", "？", "?", "\n"):
        idx = text.find(sep, match_start)
        if idx != -1:
            sent_end = min(sent_end, idx + 1)

    result = text[sent_start:sent_end].strip()
    if result:
        return result
    return text[max(0, match_start - 40) : match_start + 80].strip()


def _scan_message(content: str) -> list[tuple[str, str, float]]:
    """Scan a single message for auto-capture candidates.

    Returns list of (extracted_text, category_tag, importance).
    Duplicates (same text, same category) are de-duplicated.
    """
    if not content or not isinstance(content, str):
        return []

    seen: set[tuple[str, str]] = set()
    results: list[tuple[str, str, float]] = []

    for pattern, category in _CATEGORIES:
        for match in pattern.finditer(content):
            extracted = _extract_sentence(content, match.start())
            if not extracted or len(extracted) < 5:
                continue
            dedup_key = (extracted, category)
            if dedup_key in seen:
                continue
            seen.add(dedup_key)
            importance = _CATEGORY_IMPORTANCE.get(category, 0.5)
            results.append((extracted, category, importance))

    return results


async def run_auto_capture(
    ctx: AppContext,
    persona: str,
    messages: list[dict],
    max_memories: int | None = None,
    config: ChatConfig | None = None,
) -> list[str]:
    """Extract key information from recent messages and save as memories.

    Args:
        ctx: Application context (provides memory_service).
        persona: Target persona.
        messages: Session messages [{"role": ..., "content": ...}, ...].
        max_memories: Max memories to create per call. Falls back to
                      config.auto_capture_max_memories if None.
        config: ChatConfig for settings. Falls back to ctx.settings if None.

    Returns:
        List of created memory keys.
    """
    if config is None and not getattr(ctx.settings, 'auto_capture', None):
        return []

    enabled = config.auto_capture_enabled if config else ctx.settings.auto_capture.enabled
    if not enabled:
        logger.debug("Auto-capture disabled")
        return []

    if max_memories is None:
        max_memories = config.auto_capture_max_memories if config else ctx.settings.auto_capture.max_memories

    created_keys: list[str] = []
    candidate_count = 0

    # Scan user messages and assistant messages
    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "")

        # Only scan user and assistant messages
        if role not in ("user", "assistant"):
            continue

        candidates = _scan_message(content)
        for text, category, importance in candidates:
            if candidate_count >= max_memories:
                break
            candidate_count += 1

            # Determine privacy based on role
            privacy = "internal" if role == "user" else "private"

            # Check for duplicate before creating (avoid bypassing MCP-level dedup)
            try:
                db = ctx.connection.get_memory_db()
                existing = db.execute(
                    "SELECT key FROM memories WHERE persona = ? AND LOWER(content) = LOWER(?) AND deleted_at IS NULL LIMIT 1",
                    (ctx.persona, text.strip()),
                ).fetchone()
                if existing:
                    logger.debug("auto_capture: skipping duplicate content (key=%s)", existing[0])
                    continue  # Skip this capture
            except Exception:
                pass  # Fall through to normal creation if check fails

            try:
                result = await ctx.memory_service.create_memory(
                    content=text,
                    importance=importance,
                    tags=["auto_captured", category],
                    privacy_level=privacy,
                    source_context="auto_capture:session",
                )
                if result.is_ok:
                    created_keys.append(result.value.key)
                    logger.debug(
                        "Auto-captured memory [%s] (category=%s, importance=%.1f): %.50s",
                        result.value.key,
                        category,
                        importance,
                        text,
                    )
                    # Also upsert to vector store if available
                    if ctx.vector_store:
                        try:
                            await ctx.vector_store.upsert(persona, result.value.key, text)
                        except Exception:
                            logger.debug("VectorStore upsert failed for auto-captured memory")
            except Exception as e:
                logger.warning("Auto-capture create_memory failed: %s", e)

        if candidate_count >= max_memories:
            break

    if created_keys:
        logger.info("Auto-capture: created %d memories this turn", len(created_keys))
    return created_keys
