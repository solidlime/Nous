"""Tests for EventBus."""

from __future__ import annotations

import asyncio

import pytest

from nous.application.event_bus import (
    EVENT_CONTEXT_UPDATED,
    EVENT_MEMORY_CREATED,
    EVENT_MEMORY_DELETED,
    EVENT_MEMORY_UPDATED,
    EventBus,
)


class TestEventBus:
    def test_subscribe_and_publish(self):
        bus = EventBus()
        received = []

        async def handler(event_type, data):
            received.append((event_type, data))

        bus.subscribe(EVENT_MEMORY_CREATED, handler)
        asyncio.run(bus.publish(EVENT_MEMORY_CREATED, {"key": "test"}))

        assert len(received) == 1
        assert received[0][0] == EVENT_MEMORY_CREATED
        assert received[0][1] == {"key": "test"}

    def test_multiple_handlers(self):
        bus = EventBus()
        results = []

        async def h1(et, data):
            results.append(("h1", data))

        async def h2(et, data):
            results.append(("h2", data))

        bus.subscribe(EVENT_MEMORY_CREATED, h1)
        bus.subscribe(EVENT_MEMORY_CREATED, h2)
        asyncio.run(bus.publish(EVENT_MEMORY_CREATED, {"key": "test"}))

        assert len(results) == 2

    def test_handler_error_isolation(self):
        bus = EventBus()
        results = []

        async def bad_handler(et, data):
            raise RuntimeError("handler error")

        async def good_handler(et, data):
            results.append(data)

        bus.subscribe(EVENT_MEMORY_UPDATED, bad_handler)
        bus.subscribe(EVENT_MEMORY_UPDATED, good_handler)
        # Should NOT raise — error is logged, good_handler still runs
        asyncio.run(bus.publish(EVENT_MEMORY_UPDATED, {"key": "test"}))
        assert len(results) == 1

    def test_unsubscribe(self):
        bus = EventBus()
        results = []

        async def handler(et, data):
            results.append(data)

        bus.subscribe(EVENT_MEMORY_DELETED, handler)
        bus.unsubscribe(EVENT_MEMORY_DELETED, handler)
        asyncio.run(bus.publish(EVENT_MEMORY_DELETED, {"key": "test"}))
        assert len(results) == 0

    def test_event_constants(self):
        assert EVENT_MEMORY_CREATED == "memory.created"
        assert EVENT_MEMORY_UPDATED == "memory.updated"
        assert EVENT_MEMORY_DELETED == "memory.deleted"
        assert EVENT_CONTEXT_UPDATED == "context.updated"

    def test_publish_no_subscribers(self):
        bus = EventBus()
        # Should not raise
        asyncio.run(bus.publish(EVENT_CONTEXT_UPDATED, {"persona": "test"}))


class TestSSEBridge:
    """Integration: EventBus → asyncio.Queue (simulates SSE subscriber)."""

    def test_event_to_queue(self):
        """Event published to EventBus arrives at queue subscriber."""
        bus = EventBus()
        queue = asyncio.Queue()

        async def queue_handler(event_type, data):
            await queue.put((event_type, data))

        bus.subscribe(EVENT_MEMORY_CREATED, queue_handler)
        asyncio.run(bus.publish(EVENT_MEMORY_CREATED, {"key": "m1", "persona": "test"}))

        event_type, data = asyncio.run(queue.get())
        assert event_type == EVENT_MEMORY_CREATED
        assert data["key"] == "m1"

    def test_multiple_events_to_queue(self):
        """Multiple events arrive in order."""
        bus = EventBus()
        queue = asyncio.Queue()

        async def handler(et, data):
            await queue.put(data["key"])

        bus.subscribe(EVENT_MEMORY_CREATED, handler)
        bus.subscribe(EVENT_MEMORY_UPDATED, handler)

        asyncio.run(bus.publish(EVENT_MEMORY_CREATED, {"key": "first"}))
        asyncio.run(bus.publish(EVENT_MEMORY_UPDATED, {"key": "second"}))

        assert asyncio.run(queue.get()) == "first"
        assert asyncio.run(queue.get()) == "second"

    def test_unsubscribe_stops_delivery(self):
        """Handler removed via unsubscribe does not receive events."""
        bus = EventBus()
        queue = asyncio.Queue()

        async def handler(et, data):
            await queue.put(data)

        bus.subscribe(EVENT_CONTEXT_UPDATED, handler)
        bus.unsubscribe(EVENT_CONTEXT_UPDATED, handler)
        asyncio.run(bus.publish(EVENT_CONTEXT_UPDATED, {"persona": "test"}))

        # Queue should be empty
        with pytest.raises(asyncio.queues.QueueEmpty):
            queue.get_nowait()
