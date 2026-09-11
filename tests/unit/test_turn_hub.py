"""TurnHub unit tests: per-persona turn event hub with replay buffer."""

from __future__ import annotations

import pytest

from nous.application.chat.turn_hub import TurnHub


def _drain(queue) -> list:
    items = []
    while not queue.empty():
        items.append(queue.get_nowait())
    return items


class TestTurnLifecycle:
    @pytest.mark.asyncio
    async def test_begin_turn_returns_id(self):
        hub = TurnHub()
        turn_id = hub.begin_turn("p1")
        assert isinstance(turn_id, str) and turn_id

    @pytest.mark.asyncio
    async def test_begin_while_busy_returns_none(self):
        hub = TurnHub()
        hub.begin_turn("p1")
        assert hub.begin_turn("p1") is None

    @pytest.mark.asyncio
    async def test_end_turn_allows_new_begin(self):
        hub = TurnHub()
        hub.begin_turn("p1")
        hub.end_turn("p1")
        assert hub.begin_turn("p1") is not None

    @pytest.mark.asyncio
    async def test_personas_are_independent(self):
        hub = TurnHub()
        hub.begin_turn("p1")
        assert hub.begin_turn("p2") is not None


class TestPublish:
    @pytest.mark.asyncio
    async def test_publish_reaches_buffer_and_subscriber(self):
        hub = TurnHub()
        q = hub.subscribe("p1")
        hub.publish("p1", "data: hello\n\n")
        seq, sse = q.get_nowait()
        assert sse == "data: hello\n\n"
        assert seq == 1
        assert hub.snapshot_after("p1", 0) == [(1, "data: hello\n\n")]

    @pytest.mark.asyncio
    async def test_seq_is_monotonic_per_persona(self):
        hub = TurnHub()
        hub.publish("p1", "a")
        hub.publish("p1", "b")
        seqs = [seq for seq, _ in hub.snapshot_after("p1", 0)]
        assert seqs == [1, 2]

    @pytest.mark.asyncio
    async def test_no_subscriber_is_fine(self):
        hub = TurnHub()
        hub.publish("p1", "x")  # should not raise

    @pytest.mark.asyncio
    async def test_unsubscribed_queue_stops_receiving(self):
        hub = TurnHub()
        q = hub.subscribe("p1")
        hub.unsubscribe("p1", q)
        hub.publish("p1", "after")
        assert _drain(q) == []


class TestDropOldest:
    @pytest.mark.asyncio
    async def test_queue_overflow_drops_oldest(self):
        hub = TurnHub(queue_size=3)
        q = hub.subscribe("p1")
        for i in range(5):
            hub.publish("p1", f"e{i}")
        items = _drain(q)
        assert [sse for _, sse in items] == ["e2", "e3", "e4"]

    @pytest.mark.asyncio
    async def test_buffer_keeps_last_n(self):
        hub = TurnHub(buffer_size=3)
        q = hub.subscribe("p1")
        for i in range(5):
            hub.publish("p1", f"e{i}")
        assert [sse for _, sse in hub.snapshot_after("p1", 0)] == ["e2", "e3", "e4"]
        hub.unsubscribe("p1", q)


class TestSnapshot:
    @pytest.mark.asyncio
    async def test_snapshot_after_filters_and_orders(self):
        hub = TurnHub()
        for i in range(4):
            hub.publish("p1", f"e{i}")
        assert [(seq, sse) for seq, sse in hub.snapshot_after("p1", 2)] == [(3, "e2"), (4, "e3")]

    @pytest.mark.asyncio
    async def test_snapshot_unknown_persona_empty(self):
        hub = TurnHub()
        assert hub.snapshot_after("ghost", 0) == []

    def test_concurrent_publish_and_snapshot_are_locked(self):
        """worker スレッドの publish (deque append) と snapshot_after (反復) が
        競合して RuntimeError にならないこと。"""
        import threading

        hub = TurnHub()
        errors: list[BaseException] = []

        def writer():
            for i in range(2000):
                hub.publish("p1", f"e{i}")

        def reader():
            try:
                for _ in range(2000):
                    hub.snapshot_after("p1", 0)
            except BaseException as e:  # noqa: BLE001 - test captures any race failure
                errors.append(e)

        threads = [threading.Thread(target=writer), threading.Thread(target=reader)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert errors == []


class TestSynthetic:
    @pytest.mark.asyncio
    async def test_publish_synthetic_returns_sse(self):
        hub = TurnHub()
        q = hub.subscribe("p1")
        sse = hub.publish_synthetic("p1", {"type": "turn_started", "user_message": "hi"})
        assert sse.startswith("data: ")
        assert sse.endswith("\n\n")
        assert '"turn_started"' in sse
        seq, received = q.get_nowait()
        assert received == sse
        # bufferにも積まれる（遅延接続のリプレイ用）
        assert hub.snapshot_after("p1", 0) == [(seq, sse)]
