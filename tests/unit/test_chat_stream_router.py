"""Router tests: POST /api/chat/{persona} → 202 + hub, GET /{persona}/events SSE."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nous.api.http.routers.chat.chat_stream import chat_endpoint, chat_event_stream
from nous.application.chat.service import get_turn_hub
from nous.application.chat.turn_hub import TurnHub
from nous.domain.chat_config import ChatConfig


@pytest.fixture(autouse=True)
def _fresh_hub(monkeypatch):
    """TurnHub シングルトンをテスト毎に交換（状態リーク防止）。"""
    import nous.application.chat.service as svc

    hub = TurnHub()
    monkeypatch.setattr(svc, "_turn_hub", hub)
    yield


def _fake_request(body: dict):
    req = MagicMock()
    req.json = AsyncMock(return_value=body)
    return req


def _patch_resolver(persona: str = "test_persona", ctx=None):
    ctx = ctx or MagicMock()
    ctx.persona = persona
    return (
        patch("nous.api.http.routers.chat.chat_stream._resolve_persona_from_request", return_value=persona),
        patch("nous.api.http.routers.chat.chat_stream._safe_get_context", return_value=ctx),
        ctx,
    )


def _fake_chat(events: list[str]):
    async def fake_chat(self, ctx, config, session_id, user_message, debug=False, images=None):
        for e in events:
            yield e

    return fake_chat


class TestChatPostEndpoint:
    @pytest.mark.asyncio
    async def test_post_returns_202_with_turn_id(self):
        from nous.application.chat.service import ChatService

        events = [
            'data: {"type": "text_delta", "content": "ok"}\n\n',
            'data: {"type": "done", "message": "ok"}\n\n',
        ]
        p1, p2, ctx = _patch_resolver()
        req = _fake_request({"message": "hello", "session_id": "main"})
        hub = get_turn_hub()
        with (
            p1,
            p2,
            patch("nous.api.http.routers.chat.chat_stream.ChatConfigFileRepository") as mock_repo_cls,
            patch("nous.api.http.routers.tts.kickoff_caption_task"),
            patch.object(ChatService, "chat", _fake_chat(events)),
        ):
            mock_repo_cls.return_value.get.return_value = ChatConfig(persona="test_persona")
            resp = await chat_endpoint(req)
            assert resp.status_code == 202
            body = json.loads(bytes(resp.body))
            assert body["turn_id"]
            # タスクが完遂してバッファに done が積まれる
            for _ in range(50):
                await asyncio.sleep(0)
                if any('"done"' in sse for _, sse in hub.snapshot_after("test_persona", 0)):
                    break
        assert any('"done"' in sse for _, sse in hub.snapshot_after("test_persona", 0))

    @pytest.mark.asyncio
    async def test_post_while_busy_returns_409(self):
        from nous.application.chat.service import ChatService

        async def slow_chat(self, ctx, config, session_id, user_message, debug=False, images=None):
            await asyncio.sleep(10)
            yield 'data: {"type": "done"}\n\n'

        p1, p2, _ctx = _patch_resolver()
        req = _fake_request({"message": "hello"})
        with (
            p1,
            p2,
            patch("nous.api.http.routers.chat.chat_stream.ChatConfigFileRepository") as mock_repo_cls,
            patch("nous.api.http.routers.tts.kickoff_caption_task"),
            patch.object(ChatService, "chat", slow_chat),
        ):
            mock_repo_cls.return_value.get.return_value = ChatConfig(persona="test_persona")
            resp1 = await chat_endpoint(req)
            assert resp1.status_code == 202
            resp2 = await chat_endpoint(_fake_request({"message": "again"}))
            assert resp2.status_code == 409
            assert json.loads(bytes(resp2.body))["detail"] == "turn already running"
        get_turn_hub().end_turn("test_persona")

    @pytest.mark.asyncio
    async def test_post_persona_not_found_404(self):
        with (
            patch("nous.api.http.routers.chat.chat_stream._resolve_persona_from_request", return_value="ghost"),
            patch("nous.api.http.routers.chat.chat_stream._safe_get_context", return_value=None),
        ):
            resp = await chat_endpoint(_fake_request({"message": "hi"}))
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_post_empty_message_400(self):
        p1, p2, _ctx = _patch_resolver()
        with p1, p2:
            resp = await chat_endpoint(_fake_request({"message": "   "}))
        assert resp.status_code == 400


class TestChatEventsStream:
    @pytest.mark.asyncio
    async def test_replay_then_live_with_seq_ids(self):
        hub = get_turn_hub()
        hub.publish("test_persona", 'data: {"type": "text_delta", "content": "a"}\n\n')
        hub.publish("test_persona", 'data: {"type": "text_delta", "content": "b"}\n\n')
        q = hub.subscribe("test_persona")
        try:
            req = MagicMock()
            req.is_disconnected = AsyncMock(return_value=False)
            gen = chat_event_stream(req, "test_persona", last_seq=0)

            # リプレイ2件
            item1 = await asyncio.wait_for(gen.__anext__(), timeout=2)
            item2 = await asyncio.wait_for(gen.__anext__(), timeout=2)
            assert item1 == 'id: 1\ndata: {"type": "text_delta", "content": "a"}\n\n'
            assert item2.startswith("id: 2\n")

            # ライブ push
            hub.publish("test_persona", 'data: {"type": "done"}\n\n')
            item3 = await asyncio.wait_for(gen.__anext__(), timeout=2)
            assert item3.startswith("id: 3\n")
            assert '"done"' in item3

            await gen.aclose()
        finally:
            hub.unsubscribe("test_persona", q)

    @pytest.mark.asyncio
    async def test_replay_skips_consumed_seq(self):
        hub = get_turn_hub()
        hub.publish("test_persona", "e1")
        hub.publish("test_persona", "e2")
        q = hub.subscribe("test_persona")
        try:
            req = MagicMock()
            req.is_disconnected = AsyncMock(return_value=False)
            gen = chat_event_stream(req, "test_persona", last_seq=1)
            item = await asyncio.wait_for(gen.__anext__(), timeout=2)
            assert item.startswith("id: 2\n")
            await gen.aclose()
        finally:
            hub.unsubscribe("test_persona", q)

    @pytest.mark.asyncio
    async def test_live_duplicate_seq_is_skipped(self):
        """リプレイ済み seq がライブ側に流入しても再配信されない。"""
        hub = get_turn_hub()
        hub.publish("test_persona", "old")  # seq1
        req = MagicMock()
        req.is_disconnected = AsyncMock(return_value=False)
        gen = chat_event_stream(req, "test_persona", last_seq=0)
        replayed = await asyncio.wait_for(gen.__anext__(), timeout=2)
        assert replayed.startswith("id: 1\n")
        # gen 内部 queue にリプレイ済み seq を再投入（競合の再現）
        # _subscribers は (queue, loop) の tuple（worker スレッド配送対応のため）
        inner = hub._subscribers["test_persona"][-1][0]
        inner.put_nowait((1, "old"))
        hub.publish("test_persona", "live")  # seq2 — 積んだ重複の後ろに積まれる
        item = await asyncio.wait_for(gen.__anext__(), timeout=2)
        assert item.startswith("id: 2\n")
        assert "live" in item
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(gen.__anext__(), timeout=0.5)
        await gen.aclose()

    @pytest.mark.asyncio
    async def test_aclose_unsubscribes(self):
        hub = get_turn_hub()
        hub.publish("test_persona", "x")  # seq1 — subscribe 前なのでリプレイ対象外 (last_seq=1)
        req = MagicMock()
        req.is_disconnected = AsyncMock(return_value=False)
        gen = chat_event_stream(req, "test_persona", last_seq=1)
        hub.publish("test_persona", "y")  # seq2 ライブ
        item = await asyncio.wait_for(gen.__anext__(), timeout=2)
        assert item.startswith("id: 2\n")
        count_with_sub = len(hub._subscribers["test_persona"])
        await gen.aclose()
        assert len(hub._subscribers["test_persona"]) == count_with_sub - 1
