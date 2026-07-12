"""Episode Consolidation Pipeline: Extract factual units from episodes into Note Memory."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from nous.infrastructure.logging.structured import get_logger

logger = get_logger(__name__)

if TYPE_CHECKING:
    from nous.domain.chat_config import ChatConfig
    from nous.domain.memory.episode_segmenter import Episode

CONSOLIDATE_FACTS_PROMPT = """以下の会話エピソードから事実を抽出してください。
トピック: {topic}

会話:
{dialogue}

以下のJSON形式で回答:
{{
  "facts": [
    {{"content": "事実（日本語）", "importance": 0.7, "kind": "semantic"}}
  ],
  "preferences": [
    {{"content": "ユーザーの好み（日本語）", "importance": 0.8, "kind": "semantic"}}
  ],
  "profile_updates": [
    {{"content": "プロフィール情報（日本語）", "importance": 0.9, "kind": "semantic"}}
  ]
}}

注意:
- 重複は避けてください。新しい情報のみ抽出。
- 事実がない場合は空配列を返してください。
- 各項目には適切な importance (0.0-1.0) を設定してください。
"""


@dataclass
class ConsolidationResult:
    facts: list[dict] = field(default_factory=list)
    preferences: list[dict] = field(default_factory=list)
    profile_updates: list[dict] = field(default_factory=list)
    episodes_processed: int = 0
    memories_created: int = 0


class EpisodeConsolidation:
    """Consolidate episodes into Note Memory via LLM extraction."""

    SIMILARITY_THRESHOLD = 0.85  # dedup threshold (matches memory_llm.py)

    async def consolidate(
        self,
        episodes: list[Episode],
        memory_service: object,  # MemoryService
        session_events: list[dict] | None = None,
        ctx: object | None = None,  # AppContext
        config: ChatConfig | None = None,
        persona: str = "",
    ) -> ConsolidationResult:
        """Extract facts/preferences/profile from each episode and store as memories."""
        if not episodes:
            return ConsolidationResult()

        result = ConsolidationResult(episodes_processed=len(episodes))

        for episode in episodes:
            dialogue_lines = self._build_dialogue(episode, session_events)
            if not dialogue_lines:
                continue

            extracted = await self._extract_facts(
                dialogue=dialogue_lines,
                topic=episode.topic,
                config=config,
            )
            if not extracted:
                continue

            # Store facts
            for fact in extracted.get("facts", []):
                content = fact.get("content", "").strip()
                if not content:
                    continue
                importance = float(fact.get("importance", 0.5))
                kind = fact.get("kind", "episodic")

                if ctx is not None and hasattr(ctx, "search_engine"):
                    dup = await self._check_duplicate(ctx, content)
                    if dup:
                        continue

                if ctx is not None and hasattr(ctx, "memory_service"):
                    ctx.memory_service.create_memory(
                        content=content,
                        importance=importance,
                        tags=["episode", "episodic", "consolidated"],
                        source_type="consolidated",
                        source_context=episode.episode_id,
                        kind=kind,
                    )
                    result.memories_created += 1
                result.facts.append(fact)

            # Store preferences
            for pref in extracted.get("preferences", []):
                content = pref.get("content", "").strip()
                if not content:
                    continue
                importance = float(pref.get("importance", 0.7))
                kind = pref.get("kind", "semantic")

                if ctx is not None and hasattr(ctx, "search_engine"):
                    dup = await self._check_duplicate(ctx, content)
                    if dup:
                        continue

                if ctx is not None and hasattr(ctx, "memory_service"):
                    ctx.memory_service.create_memory(
                        content=content,
                        importance=importance,
                        tags=["episode", "preference", "consolidated"],
                        source_type="consolidated",
                        source_context=episode.episode_id,
                        kind=kind,
                    )
                    result.memories_created += 1
                result.preferences.append(pref)

            # Store profile updates
            for prof in extracted.get("profile_updates", []):
                content = prof.get("content", "").strip()
                if not content:
                    continue
                importance = float(prof.get("importance", 0.8))
                kind = prof.get("kind", "semantic")

                if ctx is not None and hasattr(ctx, "search_engine"):
                    dup = await self._check_duplicate(ctx, content)
                    if dup:
                        continue

                if ctx is not None and hasattr(ctx, "memory_service"):
                    ctx.memory_service.create_memory(
                        content=content,
                        importance=importance,
                        tags=["episode", "profile", "consolidated"],
                        source_type="consolidated",
                        source_context=episode.episode_id,
                        kind=kind,
                    )
                    result.memories_created += 1
                result.profile_updates.append(prof)

        return result

    def _build_dialogue(self, episode: Episode, session_events: list[dict] | None) -> str:
        """Build dialogue text from episode turn indices."""
        return episode.topic_summary or ""

    async def _extract_facts(
        self,
        dialogue: str,
        topic: str,
        config: ChatConfig | None = None,
    ) -> dict:
        """Call LLM to extract facts from episode dialogue."""
        if config is None:
            return {}

        api_key = config.get_effective_api_key()
        model = config.extract_model.strip() or config.get_effective_model()
        if not api_key or not model:
            return {}

        from nous.infrastructure.llm.base import DoneEvent, ErrorEvent, LLMMessage, TextDeltaEvent
        from nous.infrastructure.llm.factory import get_provider

        try:
            provider = get_provider(
                config.provider,
                api_key,
                model,
                config.get_effective_base_url(),
            )
        except Exception as e:
            logger.warning("episode_consolidation: provider init failed: %s", e, exc_info=True)
            return {}

        prompt = CONSOLIDATE_FACTS_PROMPT.format(
            topic=topic or "(未分類)",
            dialogue=dialogue or "(会話なし)",
        )

        text = ""
        try:
            async for event in provider.stream(
                messages=[LLMMessage(role="user", content=prompt)],
                system="",
                temperature=0.0,
                max_tokens=1024,
            ):
                if isinstance(event, TextDeltaEvent):
                    text += event.content
                elif isinstance(event, (DoneEvent, ErrorEvent)):
                    break
        except Exception as e:
            logger.warning("episode_consolidation: LLM call failed: %s", e, exc_info=True)
            return {}

        return self._parse_result(text)

    async def _check_duplicate(self, ctx: object, content: str) -> bool:
        """Check if similar memory already exists using semantic search."""
        try:
            from nous.domain.search.engine import SearchQuery

            if hasattr(ctx, "search_engine"):
                search_result = await ctx.search_engine.search(SearchQuery(text=content, top_k=3, mode="semantic"))
                if search_result.is_ok and search_result.value:
                    top_hit = search_result.value[0]
                    hit_score = top_hit.score if hasattr(top_hit, "score") else 0.0
                    return hit_score > self.SIMILARITY_THRESHOLD
        except Exception as e:
            logger.debug("episode_consolidation: duplicate check failed: %s", e)
        return False

    def _parse_result(self, text: str) -> dict:
        """Parse LLM JSON output."""
        text = text.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            text = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])
        try:
            result = json.loads(text)
            if not isinstance(result, dict):
                return {}
            return {
                "facts": [f for f in result.get("facts", []) if isinstance(f, dict) and f.get("content")],
                "preferences": [p for p in result.get("preferences", []) if isinstance(p, dict) and p.get("content")],
                "profile_updates": [
                    p for p in result.get("profile_updates", []) if isinstance(p, dict) and p.get("content")
                ],
            }
        except Exception as e:
            logger.warning("episode_consolidation: parse result failed: %s", e)
            return {}
