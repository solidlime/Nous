"""Memory Enricher: uses a single LLM call to auto-evaluate importance and extract entity relations."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from nous.domain.memory.contradiction import ContradictionResult, classify_contradiction
from nous.domain.memory.enrichment import EnrichmentResult, RelationCandidate
from nous.domain.value_objects import normalize_importance
from nous.infrastructure.llm.factory import get_provider

if TYPE_CHECKING:
    from nous.infrastructure.llm.base import LLMProvider

logger = logging.getLogger(__name__)

_VALID_RELATION_TYPES = frozenset(
    {
        "knows",
        "works_with",
        "manages",
        "created",
        "located_in",
        "part_of",
        "related_to",
        "summarizes",
    }
)

_SYSTEM_PROMPT = """あなたは記憶分析アシスタントです。与えられた記憶テキストを分析し、以下の2つをJSON形式で出力してください：

1. **importance**: この記憶の重要度を0.0（全く重要でない）〜1.0（極めて重要）の浮動小数点数で評価してください。
   - 0.0-0.3: 日常的な些事、一時的な感情
   - 0.4-0.6: 通常の出来事、一般的な情報
   - 0.7-0.8: 重要な出来事、強い感情を伴う体験
   - 0.9-1.0: 人生を変える出来事、核となる記憶

2. **relations**: テキスト内のエンティティ（人名、場所、概念など）間の関係性を抽出してください。
   各関係は以下の形式です：
   - source: 関係の主体（エンティティ名）
   - target: 関係の対象（エンティティ名）
   - type: 関係タイプ（knows, works_with, manages, created, located_in, part_of, related_to, summarizes のいずれか。summarizes は一方がもう一方の要約である関係）
   - confidence: 抽出の確信度（0.0〜1.0）

出力は必ず以下のJSON形式に従ってください：
{"importance": 0.5, "relations": [{"source": "entity1", "target": "entity2", "type": "knows", "confidence": 0.9}]}

関係が見つからない場合は relations を空配列にしてください。"""


class MemoryEnricher:
    """Calls LLM to extract importance + entity relations from memory content.

    All enrichment is best-effort: returns None on any failure and never blocks
    the caller.
    """

    def __init__(
        self,
        provider: str,
        api_key: str,
        model: str,
        base_url: str = "",
        min_chars: int = 10,
    ) -> None:
        self._provider_name = provider
        self._api_key = api_key
        self._model = model
        self._base_url = base_url
        self._min_chars = min_chars

    async def enrich_async(
        self,
        content: str,
        type_tags: list[str] | None = None,
        entities: list[tuple[str, str]] | None = None,
    ) -> EnrichmentResult | None:
        """One LLM call extracting both importance and entity relations (async).

        Awaits the LLM call directly so it can run as a background task
        without blocking the event loop.

        Args:
            content: Memory content to enrich.
            type_tags: Optional type tags for context.
            entities: Optional pre-extracted entity list (used as hints).

        Returns:
            EnrichmentResult on success, None on any failure.
        """
        if not content or len(content.strip()) < self._min_chars:
            return None

        # Build context from tags/entities for the LLM prompt
        context_parts: list[str] = []
        if type_tags:
            context_parts.append(f"Tags: {', '.join(type_tags)}")
        if entities:
            names = [e[0] for e in entities]
            context_parts.append(f"Known entities: {', '.join(names)}")
        context_str = "\n".join(context_parts)

        user_message = f"Analyze this memory:\n\n{content.strip()}"
        if context_str:
            user_message += f"\n\n{context_str}"

        try:
            provider = get_provider(
                provider=self._provider_name,
                api_key=self._api_key,
                model=self._model,
                base_url=self._base_url,
            )
            result_text = await self._call_llm(provider, _SYSTEM_PROMPT, user_message)
            if not result_text:
                return None
            return self._parse_response(result_text)
        except Exception:
            logger.exception("Memory enrichment failed")
            return None

    async def _call_llm(self, provider: LLMProvider, system: str, user_message: str) -> str | None:
        """Call the LLM stream and collect the full text response."""
        from nous.infrastructure.llm.base import (
            DoneEvent,
            ErrorEvent,
            LLMMessage,
            TextDeltaEvent,
        )

        full_content: list[str] = []
        async for event in provider.stream(
            messages=[LLMMessage(role="user", content=user_message)],
            system=system,
            temperature=0.3,
            max_tokens=512,
        ):
            if isinstance(event, TextDeltaEvent):
                full_content.append(event.content)
            elif isinstance(event, ErrorEvent):
                logger.warning("LLM stream error: %s", event.message)
                return None
            elif isinstance(event, DoneEvent):
                pass  # final event, ignore here
        return "".join(full_content) if full_content else None

    def _parse_response(self, text: str) -> EnrichmentResult | None:
        """Parse JSON from LLM response and return EnrichmentResult."""
        cleaned = text.strip()
        # Try to extract JSON from markdown code block if present
        if "```json" in cleaned:
            start = cleaned.index("```json") + 7
            end = cleaned.index("```", start) if "```" in cleaned[start:] else len(cleaned)
            cleaned = cleaned[start:end].strip()
        elif "```" in cleaned:
            start = cleaned.index("```") + 3
            end = cleaned.index("```", start) if "```" in cleaned[start:] else len(cleaned)
            cleaned = cleaned[start:end].strip()

        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError:
            logger.warning("Failed to parse LLM response as JSON: %s", text[:200])
            return None

        if not isinstance(data, dict):
            return None

        # Extract importance
        importance = data.get("importance", 0.5)
        if not isinstance(importance, (int, float)):
            importance = 0.5
        importance = normalize_importance(float(importance))

        # Extract relations
        relations: list[RelationCandidate] = []
        raw_relations = data.get("relations", [])
        if isinstance(raw_relations, list):
            for rel in raw_relations:
                if not isinstance(rel, dict):
                    continue
                source = str(rel.get("source", "")).strip()
                target = str(rel.get("target", "")).strip()
                rtype = str(rel.get("type", "related_to")).strip()
                confidence = rel.get("confidence", 1.0)
                if not isinstance(confidence, (int, float)):
                    confidence = 1.0
                confidence = normalize_importance(float(confidence))

                if source and target and rtype in _VALID_RELATION_TYPES:
                    relations.append(
                        RelationCandidate(
                            source_entity=source,
                            target_entity=target,
                            relation_type=rtype,
                            confidence=confidence,
                        )
                    )

        return EnrichmentResult(importance=importance, relations=relations)

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
