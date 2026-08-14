from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, Protocol

from nous.domain.shared.result import Result, Success

if TYPE_CHECKING:
    from nous.domain.shared.errors import DomainError, VectorStoreError

logger = logging.getLogger(__name__)


class ContradictionType(Enum):
    """HiMem-style 3-op classification for memory relationships."""

    INDEPENDENT = "independent"  # No relation → just ADD
    EXTENDABLE = "extendable"  # Extends existing → UPDATE metadata only
    CONTRADICTORY = "contradictory"  # Contradicts existing → invalidate old + ADD new


@dataclass
class ContradictionResult:
    """Result of contradiction classification.

    When type is EXTENDABLE, updated_fields contains the metadata changes
    (tags, context_tags, importance, etc.) to apply to the existing memory.
    When type is CONTRADICTORY, the existing memory should be tombstoned
    and the new memory saved independently.
    """

    type: ContradictionType
    existing_memory_key: str | None = None
    explanation: str = ""
    updated_fields: dict[str, Any] | None = None


CLASSIFY_PROMPT = """以下の新しい記憶と、既存の関連記憶の関係を分類してください。

新しい記憶:
{new_content}

既存の関連記憶:
{existing_contents}

以下の3つのうち1つを選んでください:
- INDEPENDENT: 新しい記憶は既存の記憶と無関係。独立した新しい事実。
- EXTENDABLE: 新しい記憶は既存の記憶を拡張・更新する情報。既存記憶のimportanceのみ更新すべき。
- CONTRADICTORY: 新しい記憶は既存の記憶と明確に矛盾する。既存記憶を無効化すべき。

既存記憶のtagsは絶対に変更しないこと。updated_fieldsで指定できるのはimportanceのみ（数値）。

JSON形式で回答:
{{"type": "INDEPENDENT|EXTENDABLE|CONTRADICTORY", "existing_key": "該当する既存記憶のkey（なければnull）", "explanation": "理由（日本語で簡潔に）", "updated_fields": {{"importance": 0.8}} }}"""


async def classify_contradiction(
    new_content: str,
    existing_memories: list[dict[str, Any]],
    llm_provider: Any,
) -> ContradictionResult | None:
    """Single LLM call: classify new vs. existing memories relationship.

    Uses one LLM call to decide whether the new memory is INDEPENDENT,
    EXTENDABLE, or CONTRADICTORY relative to existing similar memories.

    Args:
        new_content: The new memory content.
        existing_memories: List of dicts with keys 'key', 'content', 'similarity'.
        llm_provider: LLM provider (``LLMProvider`` protocol from
            ``nous.infrastructure.llm.base``).

    Returns:
        ContradictionResult on success, None on any failure (best-effort).
    """
    if not existing_memories:
        return None

    # Build existing contents string for the prompt
    parts: list[str] = []
    for i, mem in enumerate(existing_memories):
        key = mem.get("key", f"mem_{i}")
        content = mem.get("content", "")
        similarity = mem.get("similarity", 0.0)
        parts.append(f"[{i}] (key={key}, similarity={similarity:.2f})\n{content}")
    existing_contents = "\n---\n".join(parts)

    prompt = CLASSIFY_PROMPT.format(
        new_content=new_content,
        existing_contents=existing_contents,
    )

    from nous.infrastructure.llm.base import (
        ErrorEvent,
        LLMMessage,
        TextDeltaEvent,
    )

    full_content: list[str] = []
    try:
        async for event in llm_provider.stream(
            messages=[LLMMessage(role="user", content=prompt)],
            system="",
            temperature=0.3,
            max_tokens=512,
        ):
            if isinstance(event, TextDeltaEvent):
                full_content.append(event.content)
            elif isinstance(event, ErrorEvent):
                logger.warning("LLM stream error in contradiction classification: %s", event.message)
                return None
    except Exception:
        logger.exception("Contradiction classification LLM call failed")
        return None

    text = "".join(full_content) if full_content else None
    if not text:
        return None

    return _parse_contradiction_response(text)


def _parse_contradiction_response(text: str) -> ContradictionResult | None:
    """Parse JSON from LLM response into ContradictionResult."""
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
        logger.warning("Failed to parse contradiction response as JSON: %s", text[:200])
        return None

    if not isinstance(data, dict):
        return None

    raw_type = data.get("type", "")
    try:
        ctype = ContradictionType(raw_type.lower())
    except ValueError:
        logger.warning("Unknown contradiction type: %s", raw_type)
        return None

    existing_key = data.get("existing_key") or None
    explanation = data.get("explanation", "")
    raw_fields = data.get("updated_fields")

    # Whitelist: only importance may be applied to the existing memory.
    # tags / content / context_tags etc. are never applied — defense against
    # the LLM returning them despite prompt instructions.
    updated_fields: dict[str, Any] | None = None
    if isinstance(raw_fields, dict):
        importance = raw_fields.get("importance")
        if isinstance(importance, (int, float)) and not isinstance(importance, bool):
            updated_fields = {"importance": importance}

    return ContradictionResult(
        type=ctype,
        existing_memory_key=str(existing_key) if existing_key else None,
        explanation=str(explanation),
        updated_fields=updated_fields,
    )


class VectorSearchProtocol(Protocol):
    """Protocol for vector similarity search."""

    async def search(
        self, persona: str, query: str, limit: int = 10
    ) -> Result[list[tuple[str, float]], VectorStoreError]: ...


class EmbeddingProtocol(Protocol):
    """Protocol for text embedding."""

    def encode(self, text: str, *, is_query: bool = False): ...


@dataclass
class ContradictionCandidate:
    """A memory that potentially contradicts new content."""

    memory_key: str
    content: str
    similarity: float
    created_at: str


@dataclass
class ContradictionReport:
    """Report of potential contradictions found for given content."""

    query_content: str
    candidates: list[ContradictionCandidate] = field(default_factory=list)
    threshold: float = 0.85


class ContradictionDetector:
    """Vector similarity-based contradiction detection.

    Finds existing memories that are highly similar to new content,
    which may indicate contradictory or duplicate information.
    """

    def __init__(
        self,
        vector_store: VectorSearchProtocol | None = None,
        threshold: float = 0.85,
    ) -> None:
        self._vector_store = vector_store
        self._threshold = threshold

    @property
    def available(self) -> bool:
        """Whether contradiction detection is available (requires vector store)."""
        return self._vector_store is not None

    async def find_potential_contradictions(
        self,
        content: str,
        persona: str,
        exclude_key: str | None = None,
    ) -> Result[ContradictionReport, DomainError]:
        """Find existing memories that potentially contradict the given content.

        Returns memories with cosine similarity >= threshold.
        These are "similar but different" candidates that may be contradictions.
        """
        if self._vector_store is None:
            return Success(
                ContradictionReport(
                    query_content=content,
                    candidates=[],
                    threshold=self._threshold,
                )
            )

        search_result = await self._vector_store.search(persona, content, limit=10)
        if not search_result.is_ok:
            return Success(
                ContradictionReport(
                    query_content=content,
                    candidates=[],
                    threshold=self._threshold,
                )
            )

        candidates: list[ContradictionCandidate] = []
        for key, score in search_result.value:
            if exclude_key and key == exclude_key:
                continue
            if score >= self._threshold:
                candidates.append(
                    ContradictionCandidate(
                        memory_key=key,
                        content="",  # Content populated by caller if needed
                        similarity=score,
                        created_at="",
                    )
                )

        return Success(
            ContradictionReport(
                query_content=content,
                candidates=candidates,
                threshold=self._threshold,
            )
        )
