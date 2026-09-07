"""config.updated ブロードキャスト: 設定保存成功時に EventBus へ発行されること。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nous.api.http.routers.events import _ALL_EVENT_TYPES
from nous.domain.chat_config import ChatConfig


@pytest.fixture(autouse=True)
def _ctx():
    """save_chat_config に渡す疑似 AppContext。"""
    ctx = MagicMock()
    ctx.event_bus = MagicMock()
    ctx.event_bus.publish = AsyncMock()
    return ctx


def _make_request(body: dict):
    req = MagicMock()
    req.json = AsyncMock(return_value=body)
    return req


@pytest.mark.asyncio
async def test_save_config_publishes_config_updated(_ctx):
    from nous.api.http.routers.chat.chat_management import save_chat_config

    with (
        patch("nous.api.http.routers.chat.chat_management._resolve_request", return_value=("herta", _ctx)),
        patch("nous.api.http.routers.chat.chat_management.ChatConfigFileRepository") as repo_cls,
        patch.object(_ctx, "reload_enricher", MagicMock()),
    ):
        repo_cls.return_value.get.return_value = ChatConfig(persona="herta")
        repo_cls.return_value.save = MagicMock()

        resp = await save_chat_config(_make_request({"temperature": 0.5}))

    assert resp.status_code == 200
    _ctx.event_bus.publish.assert_awaited_once()
    args = _ctx.event_bus.publish.await_args
    assert args.args[0] == "config.updated"
    assert args.args[1] == {"persona": "herta"}


def test_all_event_types_contains_config_updated():
    assert "config.updated" in _ALL_EVENT_TYPES
