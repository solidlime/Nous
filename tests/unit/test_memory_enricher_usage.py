"""Usage collection tests: EnrichmentResult.usage and enrich-failure debug logging."""

from __future__ import annotations

import asyncio
import logging
from unittest.mock import MagicMock, patch

import pytest

from nous.domain.memory.enrich_service import MemoryEnrichService
from nous.infrastructure.llm.base import DoneEvent, TextDeltaEvent
from nous.infrastructure.llm.memory_enricher import MemoryEnricher


@pytest.fixture
def enricher() -> MemoryEnricher:
    return MemoryEnricher(
        provider="openrouter",
        api_key="test-key",
        model="test-model",
        base_url="https://test.url/v1",
        min_chars=10,
    )


def _async_iter(*events):
    async def _gen():
        for evt in events:
            yield evt

    return _gen()


def _enrich_with_events(enricher: MemoryEnricher, events):
    with patch("nous.infrastructure.llm.memory_enricher.get_provider") as mock:
        provider = MagicMock()
        provider.stream.return_value = _async_iter(*events)
        mock.return_value = provider
        return asyncio.run(
            enricher.enrich_async(
                content="This is a long enough memory content for enrichment.",
                type_tags=[],
                entities=[],
            )
        )


def test_usage_lands_on_result(enricher: MemoryEnricher):
    """DoneEvent.usage is collected into EnrichmentResult.usage (no instance attrs)."""
    usage = {"prompt_tokens": 950, "completion_tokens": 120, "total_tokens": 1070}
    response = '{"importance": 0.8, "relations": []}'
    result = _enrich_with_events(enricher, [TextDeltaEvent(content=response), DoneEvent(usage=usage)])

    assert result is not None
    assert result.usage == usage


def test_usage_none_when_done_has_no_usage(enricher: MemoryEnricher):
    result = _enrich_with_events(
        enricher, [TextDeltaEvent(content='{"importance": 0.5, "relations": []}'), DoneEvent()]
    )
    assert result is not None
    assert result.usage is None


def test_enrich_service_logs_failure_debug(caplog):
    """LLM failure inside enrich_memory is debug-logged, never silent."""
    enricher = MagicMock()
    enricher.enrich_async = _failing_enricher()

    from nous.domain.memory.entities import Memory
    from nous.domain.shared.time_utils import get_now

    now = get_now()
    memory = Memory(key="k1", content="some content", created_at=now.replace(tzinfo=None), updated_at=now.replace(tzinfo=None))

    service = MemoryEnrichService(enricher, None, MagicMock())
    with caplog.at_level(logging.DEBUG, logger="nous.domain.memory.enrich_service"):
        asyncio.run(service.enrich_memory(memory, "some content", None, "k1", 0.5))

    assert any("enrich failed" in r.message for r in caplog.records)


def _failing_enricher():
    async def enrich_async(**kwargs):
        raise RuntimeError("LLM down")

    return enrich_async
