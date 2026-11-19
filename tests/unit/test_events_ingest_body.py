"""Unit tests for POST /api/events/ingest body contract.

外部 Plugin (pi 本体 nous-events.ts) からの拡張型 payload の境界正規化:
- detail が dict/list でも SQLite 契約 (detail: str | None) に落とし込まれること。
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from nous.config.settings import PluginConfig

if TYPE_CHECKING:
    from nous.domain.memory.session_event import SessionEvent

pytestmark = pytest.mark.unit


def _make_env() -> SimpleNamespace:
    """有効な Plugin API を持つ最小 app と mock context を束ねる (test_plugin_auth と同パターン)。

    TestClient への動的属性付与は ruff/mypy 両方で弾かれるため SimpleNamespace で束ねる。
    """
    from tests.unit.test_plugin_auth import _make_app, _make_settings, _mock_context

    settings = _make_settings(plugin=PluginConfig(enabled=True, api_key="k"))
    client = _make_app(settings)
    return SimpleNamespace(client=client, ctx=_mock_context("herta-test", settings), settings=settings)


def _post_events(env: SimpleNamespace, events: list[dict]) -> tuple[int, dict, SessionEvent | None]:
    """POST events バッチを ingest し、(status, json, 先頭 insert 対象 SessionEvent) を返す。"""
    import nous.main as main_mod

    body = {"session_id": "sess_body", "persona": "herta-test", "events": events}
    original_getter = main_mod.get_settings
    main_mod.get_settings = lambda: env.settings  # type: ignore[assignment]
    try:
        with (
            patch(
                "nous.api.http.routers.chat.events._safe_get_context",
                return_value=env.ctx,
            ),
            patch("nous.api.http.routers.chat.events.SessionEventRepository") as repo_cls,
        ):
            resp = env.client.post("/api/events/ingest", json=body, headers={"Authorization": "Bearer k"})
            inserted = None
            if repo_cls.return_value.insert.call_args:
                inserted = repo_cls.return_value.insert.call_args[0][0]
    finally:
        main_mod.get_settings = original_getter
    return resp.status_code, resp.json(), inserted


def _post_with_event(env: SimpleNamespace, event: dict) -> tuple[int, dict, SessionEvent | None]:
    """POST 1 件の ingest を実行し、(status, json, insert 対象 SessionEvent) を返す。"""
    return _post_events(env, [event])


class TestIngestDetailBoundary:
    """detail 型境界: dict は JSON 文字列に正規化される。"""

    def test_detail_dict_becomes_json_string(self) -> None:
        env = _make_env()
        status, j, ev = _post_with_event(
            env,
            {
                "type": "turn.completed",
                "summary": "turn: smoke",
                "detail": {"user_text": "a", "tool_calls_log": [{"tool": "x"}]},
                "metadata": None,
            },
        )
        assert status == 200, j
        assert j.get("count") == 1
        assert ev is not None
        assert isinstance(ev.detail, str)

    def test_detail_string_passes_through(self) -> None:
        env = _make_env()
        status, j, ev = _post_with_event(env, {"type": "session.started", "summary": "s", "detail": "plain"})
        assert status == 200, j
        assert ev is not None
        assert ev.detail == "plain"

    def test_dict_detail_is_valid_json(self) -> None:
        import json as jsonlib

        env = _make_env()
        status, j, ev = _post_with_event(env, {"type": "turn.completed", "summary": "s", "detail": {"k": "値"}})
        assert status == 200, j
        assert ev is not None
        assert ev.detail is not None
        assert jsonlib.loads(ev.detail) == {"k": "値"}


class TestIngestConversationTime:
    """turn.completed は pi 経由の対話なので最終会話時刻を 1 回だけ記録する。"""

    def test_turn_completed_records_conversation_time_once(self) -> None:
        env = _make_env()
        status, j, _ = _post_with_event(env, {"type": "turn.completed", "summary": "turn: smoke"})
        assert status == 200, j
        env.ctx.persona_service.record_conversation_time.assert_called_once_with("herta-test")

    def test_other_events_do_not_record_conversation_time(self) -> None:
        env = _make_env()
        status, j, _ = _post_with_event(env, {"type": "session.started", "summary": "s"})
        assert status == 200, j
        env.ctx.persona_service.record_conversation_time.assert_not_called()

    def test_batch_with_multiple_turn_completed_records_once(self) -> None:
        """バッチ内に turn.completed が複数あっても record_conversation_time は 1 回だけ。"""
        env = _make_env()
        status, j, _ = _post_events(
            env,
            [
                {"type": "turn.completed", "summary": "turn: a"},
                {"type": "other.event", "summary": "x"},
                {"type": "turn.completed", "summary": "turn: b"},
            ],
        )
        assert status == 200, j
        assert j.get("count") == 3
        env.ctx.persona_service.record_conversation_time.assert_called_once_with("herta-test")
