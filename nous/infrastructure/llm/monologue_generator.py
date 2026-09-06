"""REM drain 完了時に一人称独り言を生成する (spec §4.1)。

memory_enricher._call_llm と同一の stream 消費パターンをミラーする。
失敗は静かに握る: 呼び出し側 (EnrichmentWorker) が enrichment を壊さない。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from nous.infrastructure.llm.factory import get_provider

if TYPE_CHECKING:
    from nous.infrastructure.llm.base import LLMProvider

logger = logging.getLogger(__name__)

_MAX_MEMORIES = 5
_MAX_CHARS_PER_MEMORY = 80

_SYSTEM_TEMPLATE = (
    "あなたは{persona}。今は誰もいない場所で記憶を整理している。"
    "直近で処理した記憶をもとに、一人称の独り言を1〜3文で書け。"
    "会話ではない。質問・呼びかけ・挨拶を含めない。"
)


class MonologueGenerator:
    """One LLM call per drained batch → one-person monologue text (or None)."""

    def __init__(self, provider: LLMProvider) -> None:
        self._provider = provider

    @classmethod
    def from_config(cls, provider_name: str, api_key: str, model: str, base_url: str = ""):
        """Build with the resolved brain LLM settings (same chain as MemoryEnricher)."""
        provider = get_provider(
            provider=provider_name,
            api_key=api_key,
            model=model,
            base_url=base_url or "",
        )
        return cls(provider)

    async def generate(self, persona: str, memory_texts: list[str]) -> str | None:
        """Return the monologue text for the drained memories, None on any failure."""
        if not memory_texts:
            return None
        lines = [f"- {t[:_MAX_CHARS_PER_MEMORY]}" for t in memory_texts[:_MAX_MEMORIES]]
        user_message = "処理した記憶:\n" + "\n".join(lines)
        try:
            text, _usage = await self._call_llm(_SYSTEM_TEMPLATE.format(persona=persona), user_message)
        except Exception:
            logger.debug("monologue generation failed", exc_info=True)
            return None
        return (text or "").strip() or None

    async def _call_llm(self, system: str, user_message: str) -> tuple[str | None, dict | None]:
        """memory_enricher._call_llm と同じ stream 消費パターン。"""
        from nous.infrastructure.llm.base import (
            DoneEvent,
            ErrorEvent,
            LLMMessage,
            TextDeltaEvent,
        )

        full_content: list[str] = []
        usage: dict | None = None
        async for event in self._provider.stream(
            messages=[LLMMessage(role="user", content=user_message)],
            system=system,
            temperature=0.7,
            max_tokens=200,
        ):
            if isinstance(event, TextDeltaEvent):
                full_content.append(event.content)
            elif isinstance(event, ErrorEvent):
                logger.debug("monologue LLM stream error: %s", event.message)
                return None, None
            elif isinstance(event, DoneEvent):
                usage = event.usage
                logger.debug("monologue usage: %s", usage)
        text = "".join(full_content) if full_content else None
        return text, usage
