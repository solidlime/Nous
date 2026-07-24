"""ReflectionEngine: Park et al. 2023 reflection pipeline — language-agnostic.

Provides both the legacy maybe_run_reflection (Japanese-prompt, AppContext-based)
and the new language-agnostic ReflectionEngine class.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from nous.domain.language import LanguageResolver
from nous.domain.memory.reflection_schema import OUTPUT_FORMAT, REFLECTION_SCHEMA, ReflectionQuestion
from nous.domain.search.engine import SearchQuery
from nous.infrastructure.llm.base import LLMMessage
from nous.infrastructure.llm.factory import get_provider
from nous.infrastructure.logging.structured import get_logger

if TYPE_CHECKING:
    from nous.application.use_cases import AppContext
    from nous.domain.chat_config import ChatConfig
    from nous.domain.memory.entities import Memory
    from nous.domain.memory.service import MemoryService
    from nous.infrastructure.llm.base import LLMProvider

logger = get_logger(__name__)

_REFLECTION_META_TAG = "_reflection_meta"
_REFLECTION_THRESHOLD_DEFAULT = 3.0
_REFLECTION_MIN_INTERVAL_HOURS_DEFAULT = 1.0

_REFLECTION_PROMPT = """\
Below is a list of recently recorded memories and facts.

{memories}

[Instruction]
Write in {language}.
From these memories, derive the 3 most important high-level insights.
Each insight should represent a pattern, tendency, or essential understanding — not a mere repetition of individual facts.

[Output format]
JSON only. No commentary.
{{"insights": ["insight1", "insight2", "insight3"]}}
"""

# -----------------------------------------------------------
# Legacy functions (keep for backward compatibility)
# -----------------------------------------------------------


def _get_last_reflection_at(ctx: AppContext) -> datetime | None:
    """Get the last reflection timestamp from meta-memory."""
    result = ctx.memory_service.get_by_tags([_REFLECTION_META_TAG])
    if not result.is_ok or not result.value:
        return None
    for mem in result.value:
        if mem.content.startswith("last_reflection_at:"):
            ts_str = mem.content.split(":", 1)[1].strip()
            try:
                return datetime.fromisoformat(ts_str)
            except ValueError:
                pass
    return None


def _store_last_reflection_at(ctx: AppContext, ts: datetime) -> None:
    """Store reflection timestamp as meta-memory (delete old and replace)."""
    existing = ctx.memory_service.get_by_tags([_REFLECTION_META_TAG])
    if existing.is_ok and existing.value:
        for mem in existing.value:
            if mem.content.startswith("last_reflection_at:"):
                ctx.memory_service.delete_memory(mem.key)

    ctx.memory_service.create_memory(
        content=f"last_reflection_at: {ts.isoformat()}",
        importance=0.1,
        tags=[_REFLECTION_META_TAG],
        emotion="neutral",
        persona=ctx.persona,
    )


# Per-turn reflection (⑪): 毎ターンの会話から即時的な洞察を抽出する。
# 低レイテンシ・高頻度で動作し、会話の流れに即した気づきを生成する。
# ⑫（DecayWorker経由の定期リフレクション）と併用。
async def maybe_run_reflection(
    ctx: AppContext,
    config: ChatConfig,
    recent_importance_sum: float,
) -> list[str]:
    """Run reflection when conditions are met.

    Args:
        ctx: AppContext
        config: ChatConfig
        recent_importance_sum: Sum of importance values from recently extracted facts

    Returns:
        List of generated insight strings. Empty list if reflection was skipped.
    """
    threshold: float = getattr(config, "reflection_threshold", _REFLECTION_THRESHOLD_DEFAULT)
    min_interval_hours: float = getattr(config, "reflection_min_interval_hours", _REFLECTION_MIN_INTERVAL_HOURS_DEFAULT)

    if recent_importance_sum < threshold:
        return []

    # Check that enough time has passed since the last reflection
    now = datetime.now().astimezone()
    last_at = _get_last_reflection_at(ctx)
    if last_at is not None:
        elapsed = (now - last_at).total_seconds() / 3600.0
        if elapsed < min_interval_hours:
            logger.debug(
                "Reflection skipped: last=%.1fh ago, min_interval=%.1fh",
                elapsed,
                min_interval_hours,
            )
            return []

    api_key = config.get_effective_api_key()
    extract_model = config.extract_model.strip() or config.get_effective_model()
    if not api_key or not extract_model:
        return []

    # Fetch up to 20 memories from the last 24 hours
    cutoff = now - timedelta(hours=24)
    recent_result = ctx.memory_service.get_recent(limit=20)
    if not recent_result.is_ok or not recent_result.value:
        # Fallback: use smart search to get recent memories
        search_result = await ctx.search_engine.search(SearchQuery(text="記憶 事実 出来事", top_k=20, mode="hybrid"))
        memories = []
        if search_result.is_ok:
            for item in search_result.value:
                mem = item[0] if isinstance(item, tuple) else item
                memories.append(mem)
    else:
        memories = [m for m in recent_result.value if m.created_at >= cutoff] or recent_result.value[:10]

    if not memories:
        return []

    language_resolver = LanguageResolver(config)
    lang = language_resolver.resolve()
    memory_lines = "\n".join(f"- [{m.importance:.1f}] {m.content[:120]}" for m in memories[:20])
    prompt = _REFLECTION_PROMPT.format(
        memories=memory_lines,
        language=LanguageResolver.display_name(lang),
    )

    try:
        provider = get_provider(config.provider, api_key, extract_model, config.get_effective_base_url())
    except Exception as e:
        logger.warning("ReflectionEngine: provider init failed: %s", e)
        return []

    from nous.infrastructure.llm.base import DoneEvent, ErrorEvent, TextDeltaEvent

    text = ""
    try:
        async for event in provider.stream(
            messages=[LLMMessage(role="user", content=prompt)],
            system="",
            tools=[],
            temperature=0.3,
            max_tokens=512,
        ):
            if isinstance(event, TextDeltaEvent):
                text += event.content
            elif isinstance(event, (DoneEvent, ErrorEvent)):
                break
    except Exception as e:
        logger.warning("ReflectionEngine: LLM call failed: %s", e)
        return []

    insights = _parse_insights(text)
    if not insights:
        return []

    for insight in insights:
        ctx.memory_service.create_memory(
            content=insight,
            importance=0.9,
            tags=["reflection"],
            emotion="neutral",
            persona=ctx.persona,
        )

    _store_last_reflection_at(ctx, now)
    logger.info("ReflectionEngine: stored %d insights for persona=%s", len(insights), ctx.persona)
    return insights


def _parse_insights(text: str) -> list[str]:
    """Parse insight list from LLM output."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])
    try:
        result = json.loads(text)
        if isinstance(result, dict):
            insights = result.get("insights", [])
            return [s for s in insights if isinstance(s, str) and s.strip()]
    except Exception:
        pass
    return []


# -----------------------------------------------------------
# New language-agnostic ReflectionEngine (Park et al. 2023)
# -----------------------------------------------------------

# Periodic reflection (⑫): 24時間周期で全記憶を対象に深い洞察を抽出する。
# 高レイテンシ・低頻度で動作し、長期的なパターンや変化を捉える。
# ⑪（ターンごとの即時リフレクション）と併用。


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
        from nous.infrastructure.llm.base import DoneEvent, ErrorEvent, TextDeltaEvent

        text = ""
        try:
            async for event in llm.stream(
                messages=messages or [LLMMessage(role="user", content=system_msg)],
                system=effective_system if not messages else "",
                tools=[],
                temperature=temperature,
                max_tokens=max_tokens,
            ):
                if isinstance(event, TextDeltaEvent):
                    text += event.content
                elif isinstance(event, (DoneEvent, ErrorEvent)):
                    break
        except Exception as exc:
            self._logger.warning("ReflectionEngine: LLM call failed: %s", exc)
            return []

        # 4. Parse structured output
        insights = self._parse_insights_json(text)
        if not insights:
            return []

        # 5. Persist as semantic memories
        results: list[dict[str, Any]] = []
        for insight in insights:
            content = insight.get("insight", "")
            if not content:
                continue
            mem_result = memory_service.create_memory(
                persona=persona,
                content=content,
                kind="semantic",
                source_type="reflected",
                confidence=insight.get("confidence", 0.7),
                importance=0.8,
                tags=["reflection"],
            )
            if mem_result.is_ok:
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
        memory_lines = "\n".join(f"- {getattr(m, 'content', str(m))}" for m in memories[-30:])

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
            "The reflection should reveal patterns, traits, or implications "
            "that are NOT explicitly stated in individual memories."
        )

    @staticmethod
    def _parse_insights_json(text: str) -> list[dict[str, Any]]:
        """Parse the structured LLM output into a list of insight dicts.

        Handles both raw JSON and code-fenced JSON.
        """
        text = text.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            text = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])
            text = text.strip()

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
