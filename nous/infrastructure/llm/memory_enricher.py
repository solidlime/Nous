"""矛盾判定専用の LLM クライアント。

記憶の enrichment（importance 推定・関係抽出）は廃止（2026-11-08, kanban #29）。
importance は書き込み時の既定 0.5 固定で存置。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from nous.domain.memory.contradiction import ContradictionResult, classify_contradiction
from nous.infrastructure.llm.factory import get_provider
from nous.infrastructure.llm.text_utils import collect_text_with_usage

if TYPE_CHECKING:
    from nous.infrastructure.llm.base import LLMProvider

logger = logging.getLogger(__name__)


class MemoryEnricher:
    """LLM で既存記憶との関係（独立/拡張/矛盾）を判定する薄いラッパー。

    best-effort: 失敗は None を返し、呼び出し元を止めない。
    """

    def __init__(
        self,
        provider: str,
        api_key: str,
        model: str,
        base_url: str = "",
        reasoning_effort: str | None = None,
        max_tokens: int = 512,
        temperature: float = 0.3,
        session_id: str | None = None,
    ) -> None:
        self._provider_name = provider
        self._api_key = api_key
        self._model = model
        self._base_url = base_url
        # 脳専用 reasoning トグル (chat の reasoning とは独立)。None なら effort を渡さない。
        self._reasoning_effort = reasoning_effort
        self._max_tokens = max_tokens
        self._temperature = temperature
        # OpenCode Go 用の安定セッションID (persona ベース、例: nous-brain-<persona>)
        self._session_id = session_id

    async def _call_llm(self, provider: LLMProvider, system: str, user_message: str) -> tuple[str | None, dict | None]:
        """Call the LLM stream and collect the full text response plus token usage."""
        from nous.infrastructure.llm.base import LLMMessage

        collected = await collect_text_with_usage(
            provider,
            messages=[LLMMessage(role="user", content=user_message)],
            system=system,
            temperature=self._temperature,
            max_tokens=self._max_tokens,
            reasoning_effort=self._reasoning_effort,
        )
        return collected.text, collected.usage

    async def classify_contradiction(
        self,
        new_content: str,
        existing_memories: list[dict],
    ) -> ContradictionResult | None:
        """Classify the relationship between new and existing memories via LLM.

        Uses a single LLM call to decide if the new memory is INDEPENDENT,
        EXTENDABLE, or CONTRADICTORY relative to the provided existing memories.

        Async so it can be awaited from background tasks without blocking the
        event loop.

        Best-effort: returns None on any failure and never blocks the caller.

        Args:
            new_content: New memory content to classify.
            existing_memories: List of dicts with keys 'key', 'content',
                'similarity' representing similar existing memories.

        Returns:
            ContradictionResult on success, None on any failure.
        """
        if not new_content or not existing_memories:
            return None

        try:
            provider = get_provider(
                provider=self._provider_name,
                api_key=self._api_key,
                model=self._model,
                base_url=self._base_url,
                session_id=self._session_id,
            )
            result = await classify_contradiction(
                new_content=new_content,
                existing_memories=existing_memories,
                llm_provider=provider,
            )
            return result
        except Exception:
            logger.exception("Contradiction classification failed")
            return None
