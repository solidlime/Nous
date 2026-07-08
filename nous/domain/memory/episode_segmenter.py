"""Episode Segmenter: HiMem-style topic shift detection + surprise scoring.

Segments conversation turns into Episodes based on topic changes and
unexpectedness (surprise) signals.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nous.domain.chat_config import ChatConfig

SEGMENT_PROMPT = """以下の会話の続きを分析してください。

前の会話のトピック: {prev_topic}

新しい発言:
User: {user_msg}
Assistant: {assistant_msg}

以下の3つの質問にJSON形式で回答:
1. topic_changed: トピックが前の会話から大きく変わったか？ (true/false)
2. surprise_score: ユーザーの発言が予想外か？ (0.0-1.0)
3. new_topic: 新しいトピック名（変わった場合のみ、日本語で簡潔に）

{{"topic_changed": false, "surprise_score": 0.2, "new_topic": ""}}"""


@dataclass
class Episode:
    episode_id: str
    start_index: int  # session event index (turn pair index)
    end_index: int
    topic: str  # LLMが判定したトピック
    topic_summary: str  # トピックの要約
    surprise_score: float  # 0.0-1.0
    created_at: datetime = field(default_factory=datetime.now)


@dataclass
class SegmentationResult:
    episodes: list[Episode] = field(default_factory=list)
    skipped_turns: int = 0


class EpisodeSegmenter:
    """Segment conversation turns into Episodes using LLM-based analysis."""

    MIN_SEGMENT_LENGTH = 3  # minimum turns per segment

    async def segment(
        self,
        messages: list[dict],
        llm_provider_name: str = "anthropic",
        llm_api_key: str = "",
        llm_model: str = "",
        llm_base_url: str = "",
        config: ChatConfig | None = None,
    ) -> SegmentationResult:
        """Segment a list of conversation messages into Episodes.

        Args:
            messages: List of dicts with 'role' and 'content' keys
                (same format as SessionWindow._messages).
            llm_provider_name: Provider name for LLM calls.
            llm_api_key: API key for LLM calls.
            llm_model: Model name for LLM calls.
            llm_base_url: Base URL for LLM provider.
            config: Optional ChatConfig to derive LLM settings from.

        Returns:
            SegmentationResult with list of Episode objects.
        """
        if config is not None:
            llm_api_key = llm_api_key or config.get_effective_api_key()
            llm_model = llm_model or config.extract_model.strip() or config.get_effective_model()
            llm_provider_name = llm_provider_name or config.provider
            llm_base_url = llm_base_url or config.get_effective_base_url()

        if not llm_api_key or not llm_model:
            return SegmentationResult()

        # Build turn pairs (list of (user_msg, assistant_msg))
        turns: list[tuple[str, str]] = []
        for i in range(0, len(messages) - 1, 2):
            if messages[i]["role"] == "user" and messages[i + 1]["role"] == "assistant":
                turns.append((messages[i]["content"], messages[i + 1]["content"]))

        if not turns:
            return SegmentationResult()

        # Run segmentation
        segments: list[list[int]] = []  # list of turn index ranges
        current_segment: list[int] = []
        prev_topic = "(会話開始)"

        from nous.infrastructure.llm.base import DoneEvent, ErrorEvent, LLMMessage, TextDeltaEvent
        from nous.infrastructure.llm.factory import get_provider

        try:
            provider = get_provider(llm_provider_name, llm_api_key, llm_model, llm_base_url)
        except Exception:
            # Fallback: single segment
            return SegmentationResult(
                episodes=[self._build_episode(turns, 0, len(turns) - 1, prev_topic)],
            )

        for idx, (user_msg, assistant_msg) in enumerate(turns):
            prompt = SEGMENT_PROMPT.format(
                prev_topic=prev_topic,
                user_msg=user_msg[:300],
                assistant_msg=assistant_msg[:300],
            )

            text = ""
            try:
                async for event in provider.stream(
                    messages=[LLMMessage(role="user", content=prompt)],
                    system="",
                    temperature=0.0,
                    max_tokens=200,
                ):
                    if isinstance(event, TextDeltaEvent):
                        text += event.content
                    elif isinstance(event, (DoneEvent, ErrorEvent)):
                        break
            except Exception:
                # On error, continue current segment
                current_segment.append(idx)
                continue

            try:
                result = json.loads(self._clean_json(text))
                topic_changed = result.get("topic_changed", False)
                surprise_score = float(result.get("surprise_score", 0.0))
                new_topic = result.get("new_topic", "")

                if topic_changed or surprise_score > 0.7:
                    # Boundary detected: finalize current segment if non-empty
                    if current_segment:
                        segments.append(list(current_segment))
                    # Start new segment
                    current_segment = [idx]

                    if new_topic:
                        prev_topic = new_topic
                    elif surprise_score > 0.7:
                        prev_topic = f"予想外の話題 (surprise={surprise_score:.1f})"
                else:
                    current_segment.append(idx)

            except (json.JSONDecodeError, KeyError, ValueError):
                current_segment.append(idx)

        # Finalize last segment
        if current_segment:
            segments.append(list(current_segment))

        # Merge short segments (< MIN_SEGMENT_LENGTH)
        segments = self._merge_short_segments(segments)

        # Build Episode objects
        episodes = []
        for seg in segments:
            if not seg:
                continue
            ep = self._build_episode(turns, seg[0], seg[-1], prev_topic)
            episodes.append(ep)

        return SegmentationResult(episodes=episodes)

    def _build_episode(
        self,
        turns: list[tuple[str, str]],
        start_idx: int,
        end_idx: int,
        topic: str,
    ) -> Episode:
        """Build an Episode from a range of turn indices."""
        from nous.domain.shared.time_utils import generate_memory_key

        # Extract dialogue text for summary
        dialogue_lines = []
        for i in range(start_idx, end_idx + 1):
            if i < len(turns):
                dialogue_lines.append(f"User: {turns[i][0][:100]}")
                dialogue_lines.append(f"Assistant: {turns[i][1][:100]}")
        topic_summary = "\n".join(dialogue_lines[:6])  # keep it brief

        return Episode(
            episode_id=f"ep_{generate_memory_key()}",
            start_index=start_idx,
            end_index=end_idx,
            topic=topic,
            topic_summary=topic_summary,
            surprise_score=0.0,
        )

    def _merge_short_segments(self, segments: list[list[int]], min_len: int | None = None) -> list[list[int]]:
        """Merge segments shorter than min_len into the previous segment."""
        if min_len is None:
            min_len = self.MIN_SEGMENT_LENGTH
        if not segments:
            return segments

        merged: list[list[int]] = [list(segments[0])]
        for seg in segments[1:]:
            if len(seg) < min_len and merged:
                # Merge into previous segment
                merged[-1].extend(seg)
            else:
                merged.append(list(seg))
        return merged

    @staticmethod
    def _clean_json(text: str) -> str:
        """Extract JSON object from LLM response, handling markdown fences."""
        text = text.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            text = "\n".join(lines[1:-1] if len(lines) > 1 and lines[-1].startswith("```") else lines[1:])
        return text.strip()
