"""ReflectionEngine: Park et al. 2023 reflection pipeline — language-agnostic.

Periodic structured reflection, wired into DecayWorker (every
``DecayWorker.REFLECTION_INTERVAL`` decay cycles).  The legacy per-turn
``maybe_run_reflection`` (meta-memory timestamp tracking) was removed — the
periodic engine covers both low- and high-frequency conversations.
"""

from __future__ import annotations

import json
import math
from collections import Counter
from typing import TYPE_CHECKING, Any

from nous.domain.language import LanguageResolver
from nous.domain.memory.reflection_schema import OUTPUT_FORMAT, REFLECTION_SCHEMA, ReflectionQuestion
from nous.domain.shared.text_utils import strip_code_fence
from nous.domain.shared.time_utils import relative_time_str
from nous.infrastructure.llm.base import LLMMessage
from nous.infrastructure.llm.text_utils import collect_text
from nous.infrastructure.logging.structured import get_logger

if TYPE_CHECKING:
    from nous.domain.chat_config import ChatConfig
    from nous.domain.memory.entities import Memory
    from nous.domain.memory.service import MemoryService
    from nous.infrastructure.llm.base import LLMProvider

logger = get_logger(__name__)

# Dedup: skip insights too similar to existing reflection memories
# (same pattern as memory_extractor.py fact dedup, threshold 0.85).
_DEDUP_THRESHOLD = 0.85
_DEDUP_SCAN_LIMIT = 100


def _cosine_similarity(a: str, b: str) -> float:
    """Character-bigram cosine similarity (language-agnostic, 0.0-1.0).

    Bigrams work for CJK without a tokenizer; near-identical paraphrases
    score high, unrelated sentences score low.
    """

    def bigrams(text: str) -> Counter[str]:
        return Counter(text[i : i + 2] for i in range(len(text) - 1))

    va, vb = bigrams(a), bigrams(b)
    if not va or not vb:
        return 0.0
    dot = sum(n * vb[g] for g, n in va.items())
    na = math.sqrt(sum(n * n for n in va.values()))
    nb = math.sqrt(sum(n * n for n in vb.values()))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def _is_duplicate_insight(content: str, existing_contents: list[str], threshold: float = _DEDUP_THRESHOLD) -> bool:
    """True when *content* is too similar to any existing reflection memory."""
    return any(_cosine_similarity(content, existing) > threshold for existing in existing_contents)


def _memory_time_suffix(memory: Any) -> str:
    """Relative-time suffix for a memory line, anchored on created_at.

    Returns " (3mo ago)"-style text, or "" when no created_at is available.
    """
    created_at = getattr(memory, "created_at", None)
    if not created_at:
        return ""
    return f" ({relative_time_str(created_at)})"


def _reflection_contents(memory_service: MemoryService) -> list[str]:
    """Contents of recent reflection-tagged memories (cheapest dedup source).

    Non-list results (mocked services) are treated as empty.
    """
    try:
        result = memory_service.get_by_tags(["reflection"])
    except Exception:
        logger.warning(
            "_reflection_contents: get_by_tags(reflection) failed, skipping dedup scan",
            exc_info=True,
        )
        return []
    values = getattr(result, "value", None)
    if result.is_ok and isinstance(values, list):
        return [str(m.content) for m in values[-_DEDUP_SCAN_LIMIT:]]
    return []


class ReflectionEngine:
    """Language-agnostic reflection pipeline (Park et al. 2023).

    Synthesizes high-level insights from recent episodic memories using
    configurable reflection questions.  Uses ``llm.stream()`` internally
    and parses structured JSON output.
    """

    MIN_MEMORIES = 10
    DEFAULT_LIMIT = 50

    def __init__(
        self,
        schema: list[ReflectionQuestion] | None = None,
        logger: Any | None = None,
        config: ChatConfig | None = None,
    ) -> None:
        self._schema = schema or REFLECTION_SCHEMA
        self._logger = logger or get_logger(self.__class__.__name__)
        self._config = config

    # ---- public API ---------------------------------------------------

    async def reflect(
        self,
        persona: str,
        memory_service: MemoryService,
        llm: LLMProvider,
        *,
        limit: int | None = None,
        temperature: float = 0.3,
        max_tokens: int = 1024,
        system_prompt: str | None = None,
    ) -> list[dict[str, Any]]:
        """Run one reflection cycle.

        Args:
            persona: Persona name (used in the system message).
            memory_service: Domain memory service.
            llm: LLM provider with a ``stream()`` method.
            limit: Max recent memories to fetch (default ``DEFAULT_LIMIT``).
            temperature: LLM temperature.
            max_tokens: Max tokens for the response.
            system_prompt: Optional system prompt override.

        Returns:
            List of insight dicts ``{"insight": str, "evidence_keys": list, "confidence": float}``.
            Empty list when there are fewer than ``MIN_MEMORIES`` memories.
        """
        # 1. Fetch recent memories
        recent_result = memory_service.get_recent(limit=limit or self.DEFAULT_LIMIT)
        if not recent_result.is_ok or not recent_result.value:
            return []
        memories: list[Memory] = recent_result.value

        if len(memories) < self.MIN_MEMORIES:
            return []

        # 2. Build system message
        system_msg = self._build_system_message(persona, memories)

        effective_system = system_prompt or system_msg
        prompt_msg = system_msg if system_prompt else ""
        messages = [LLMMessage(role="user", content=prompt_msg)] if prompt_msg else []
        if system_prompt:
            messages = [LLMMessage(role="user", content=system_msg)]

        # 3. Call LLM
        try:
            text = await collect_text(
                llm,
                messages=messages or [LLMMessage(role="user", content=system_msg)],
                system=effective_system if not messages else "",
                tools=[],
                temperature=temperature,
                max_tokens=max_tokens,
            )
        except Exception as exc:
            self._logger.warning("ReflectionEngine: LLM call failed: %s", exc)
            return []

        # 4. Parse structured output
        insights = self._parse_insights_json(text or "")
        if not insights:
            return []

        # 5. Persist as semantic memories (with dedup + evidence link)
        existing_contents = _reflection_contents(memory_service)
        results: list[dict[str, Any]] = []
        for insight in insights:
            content = insight.get("insight", "")
            if not content:
                continue
            if _is_duplicate_insight(content, existing_contents):
                self._logger.info("ReflectionEngine: duplicate insight skipped: %s", content[:60])
                continue
            evidence = insight.get("evidence_keys")
            save_kwargs: dict[str, Any] = {}
            if isinstance(evidence, list):
                keys = [k for k in evidence if isinstance(k, str) and k]
                if keys:
                    save_kwargs["related_keys"] = keys
            mem_result = await memory_service.create_memory(
                persona=persona,
                content=content,
                kind="semantic",
                source_type="reflected",
                confidence=insight.get("confidence", 0.7),
                importance=0.8,
                tags=["reflection"],
                **save_kwargs,
            )
            if mem_result.is_ok:
                existing_contents.append(content)
                results.append(insight)
        self._logger.info(
            "ReflectionEngine: stored %d insights for persona=%s",
            len(results),
            persona,
        )
        return results

    # ---- internal helpers ---------------------------------------------

    def _build_system_message(self, persona: str, memories: list[Memory]) -> str:
        """Build the language-agnostic reflection prompt."""
        schema_desc = json.dumps(
            [{"id": q.id, "intent": q.intent, "output": q.output_key} for q in self._schema],
            ensure_ascii=False,
        )
        memory_lines = "\n".join(f"- {getattr(m, 'content', str(m))}{_memory_time_suffix(m)}" for m in memories[-30:])

        if self._config is not None:
            resolver = LanguageResolver(self._config)
            lang = resolver.resolve()
            language_name = LanguageResolver.display_name(lang)
        else:
            language_name = "English"

        return (
            f"You are {persona}. Analyze the recent memories and generate insights.\n\n"
            f"Reflection tasks:\n{schema_desc}\n\n"
            f"Output format: {json.dumps(OUTPUT_FORMAT, ensure_ascii=False)}\n\n"
            f"Recent memories:\n{memory_lines}\n\n"
            f"Generate insights in {language_name}. "
            "Write each insight in first person as that character (そのキャラクター自身の一人称で書くこと。キャラ名呼びの三人称は禁止). "
            "The reflection should reveal patterns, traits, or implications "
            "that are NOT explicitly stated in individual memories. "
            "Consider the time shown in parentheses for each memory; do not conflate old memories with recent events "
            "(各記憶の括弧内の時刻を考慮し、古い記憶と直近の出来事を混同しないこと)。"
        )

    @staticmethod
    def _parse_insights_json(text: str) -> list[dict[str, Any]]:
        """Parse the structured LLM output into a list of insight dicts.

        Handles both raw JSON and code-fenced JSON.
        """
        text = strip_code_fence(text)

        try:
            result = json.loads(text)
        except json.JSONDecodeError:
            return []

        if isinstance(result, list):
            # Direct array of insight objects
            validated: list[dict[str, Any]] = []
            for item in result:
                if isinstance(item, dict) and item.get("insight"):
                    validated.append(item)
            return validated

        if isinstance(result, dict):
            # Maybe it has an "insights" key
            items = result.get("insights") or result.get("data") or result.get("reflections") or result.get("items")
            if isinstance(items, list):
                validated = []
                for item in items:
                    if isinstance(item, dict) and item.get("insight"):
                        validated.append(item)
                return validated
            # Single insight object
            if result.get("insight"):
                return [result]
        return []
