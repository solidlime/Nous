"""自発ターンがユーザーターンと重ならないこと（kanban #67）。"""

from __future__ import annotations

import asyncio
import logging
from unittest.mock import MagicMock, patch

import pytest

from nous.application.chat.tools.schedule import run_self_turn
from nous.application.chat.turn_hub import TurnHub

PERSONA = "herta"


def test_background_turn_excluded_by_user_turn():
    hub = TurnHub()
    assert hub.begin_turn(PERSONA) is not None
    assert hub.begin_background_turn(PERSONA) is False
    hub.end_turn(PERSONA)
    assert hub.begin_background_turn(PERSONA) is True


def test_background_turns_exclude_each_other():
    hub = TurnHub()
    assert hub.begin_background_turn(PERSONA) is True
    assert hub.begin_background_turn(PERSONA) is False
    hub.end_background_turn(PERSONA)
    assert hub.begin_background_turn(PERSONA) is True


def test_is_running_sees_background_turn():
    hub = TurnHub()
    hub.begin_background_turn(PERSONA)
    assert hub.is_running(PERSONA) is True


def test_run_self_turn_skips_while_user_turn_runs(caplog):
    """ユーザーターン中は1手も推論せず、実行ループを回さない。"""
    hub = TurnHub()
    hub.begin_turn(PERSONA)
    ctx = MagicMock()
    ctx.persona = PERSONA
    ctx.config = MagicMock()

    with (
        patch("nous.application.chat.service.get_turn_hub", return_value=hub),
        patch("nous.application.chat.service.ChatService") as chat_cls,
        caplog.at_level(logging.INFO),
    ):
        assert asyncio.run(run_self_turn(ctx, "なにか")) is None
        chat_cls.return_value.chat.assert_not_called()

    assert "skip" in caplog.text


def test_run_self_turn_releases_background_slot():
    """ターン中に例外が出ても自発スロットは解放される（次 tick が詰まらない）。"""
    hub = TurnHub()
    ctx = MagicMock()
    ctx.persona = PERSONA
    ctx.config = MagicMock()

    class _Boom:
        async def __aiter__(self):
            raise RuntimeError("boom")
            yield  # pragma: no cover

    with (
        patch("nous.application.chat.service.get_turn_hub", return_value=hub),
        patch("nous.application.chat.service.ChatService") as chat_cls,
    ):
        chat_cls.return_value.chat.return_value = _Boom()
        with pytest.raises(RuntimeError):
            asyncio.run(run_self_turn(ctx, "なにか"))

    assert hub.begin_background_turn(PERSONA) is True
