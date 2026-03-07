import logging

logger = logging.getLogger(__name__)


class ElevationBatchProcessor:
    def __init__(self, llm_router, memory_db, config: dict):
        self.llm_router = llm_router
        self.memory_db = memory_db
        self.config = config
        self._elevator = None

    def _get_elevator(self):
        if self._elevator is None:
            from elevation.elevate import MemoryElevator
            self._elevator = MemoryElevator(self.llm_router, self.memory_db)
        return self._elevator

    async def run_batch(
        self,
        persona: str,
        batch_size: int = 10,
        min_importance: float = 0.3,
        dry_run: bool = False,
    ) -> dict:
        try:
            entries = self.memory_db.get_unelevated(
                min_importance=min_importance, limit=batch_size
            )
            if not entries:
                return {"processed": 0, "skipped": 0, "errors": [], "dry_run": dry_run}

            if dry_run:
                from elevation.prompts import build_elevation_prompt

                sample = entries[0]
                preview = build_elevation_prompt({
                    "created_at": sample.created_at,
                    "content": sample.content,
                    "emotion": sample.emotion,
                    "emotion_intensity": sample.emotion_intensity,
                    "tags": sample.tags,
                    "importance": sample.importance,
                })
                return {
                    "processed": 0,
                    "skipped": len(entries),
                    "errors": [],
                    "dry_run": True,
                    "sample_count": len(entries),
                    "sample_key": sample.key,
                    "sample_prompt_preview": preview[:300],
                }

            elevator = self._get_elevator()
            api_interval = self.config.get("elevation", {}).get("api_interval_sec", 2.0)
            results = await elevator.elevate_batch(entries, api_interval=api_interval)

            processed = sum(1 for r in results if r is not None)
            skipped = len(results) - processed
            errors = [f"Failed: {entries[i].key}" for i, r in enumerate(results) if r is None]

            logger.info(f"[{persona}] Elevation: {processed} processed, {skipped} skipped")
            return {"processed": processed, "skipped": skipped, "errors": errors, "dry_run": False}

        except Exception as e:
            logger.error(f"Batch elevation error: {e}")
            return {"processed": 0, "skipped": 0, "errors": [str(e)], "dry_run": dry_run}
