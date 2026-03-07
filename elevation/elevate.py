import json
import re
import logging
from datetime import datetime
from typing import Optional
from llm.base import Message

logger = logging.getLogger(__name__)


class MemoryElevator:
    def __init__(self, llm_router, memory_db):
        self.llm_router = llm_router
        self.memory_db = memory_db

    async def elevate(self, entry) -> Optional[object]:
        from elevation.prompts import ELEVATION_SYSTEM_PROMPT, build_elevation_prompt

        entry_dict = {
            "created_at": entry.created_at,
            "content": entry.content,
            "emotion": entry.emotion,
            "emotion_intensity": entry.emotion_intensity,
            "tags": entry.tags,
            "importance": entry.importance,
        }
        messages = [
            Message(role="system", content=ELEVATION_SYSTEM_PROMPT),
            Message(role="user", content=build_elevation_prompt(entry_dict)),
        ]
        try:
            response = await self.llm_router.generate(
                messages=messages,
                task_type="memory_elevation",
                max_tokens=500,
                temperature=0.8,
            )
            if response.error or not response.content:
                logger.warning(f"Elevation failed for {entry.key}: {response.error}")
                return None

            result = self._parse_elevation_response(response.content)
            if not result:
                return None

            success = self.memory_db.update_elevation(
                key=entry.key,
                narrative=result["narrative"],
                emotion=result["emotion"],
                significance=result["significance"],
            )
            if success:
                entry.elevated = True
                entry.elevation_at = datetime.now().isoformat()
                entry.elevation_narrative = result["narrative"]
                entry.elevation_emotion = result["emotion"]
                entry.elevation_significance = result["significance"]
                return entry
            return None

        except Exception as e:
            logger.error(f"Elevation error for {entry.key}: {e}")
            return None

    def _parse_elevation_response(self, content: str) -> Optional[dict]:
        content = re.sub(r"```json\s*|\s*```", "", content).strip()
        try:
            result = json.loads(content)
            if "narrative" not in result:
                result["narrative"] = content[:200]
            valid_emotions = ["joy", "curiosity", "nostalgia", "melancholy", "pride", "neutral"]
            if result.get("emotion") not in valid_emotions:
                result["emotion"] = "neutral"
            result["significance"] = max(0.0, min(1.0, float(result.get("significance", 0.5))))
            return result
        except (json.JSONDecodeError, ValueError):
            logger.warning(f"Failed to parse elevation JSON: {content[:100]}")
            return None

    async def elevate_batch(self, entries: list, api_interval: float = 2.0) -> list:
        import asyncio

        results = []
        for entry in entries:
            result = await self.elevate(entry)
            results.append(result)
            await asyncio.sleep(api_interval)
        return results
