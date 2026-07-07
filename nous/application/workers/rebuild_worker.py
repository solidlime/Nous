from __future__ import annotations

from typing import TYPE_CHECKING

from nous.domain.shared.errors import DomainError, VectorStoreError
from nous.domain.shared.result import Failure, Success
from nous.infrastructure.logging.structured import get_logger

if TYPE_CHECKING:
    from nous.application.use_cases import AppContext

logger = get_logger(__name__)


class RebuildWorker:
    """Vector store rebuild worker."""

    def __init__(self, context: AppContext) -> None:
        self.context = context

    async def rebuild(self) -> Success[int] | Failure[DomainError]:
        """Rebuild vector store from SQLite data. Returns count of vectors rebuilt."""
        memories_result = self.context.memory_repo.find_all()
        if not memories_result.is_ok:
            return Failure(memories_result.error)

        vs = self.context.vector_store
        if vs is None:
            return Failure(VectorStoreError("Qdrant not available"))

        count = 0
        for memory in memories_result.value:
            upsert_result = await vs.upsert(
                self.context.persona,
                memory.key,
                memory.content,
                {
                    "importance": memory.importance,
                    "emotion": memory.emotion,
                    "tags": ",".join(memory.tags),
                },
            )
            if upsert_result.is_ok:
                count += 1

        logger.info("Vector store rebuilt: %d vectors", count)
        return Success(count)
