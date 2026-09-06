from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nous.api.http.sections.chat import render_chat_tab
from nous.application.chat.events import _sse_encode as _sse
from nous.application.chat.session_store import TreeSessionWindow
from nous.application.chat_service import SessionManager
from nous.domain.chat_config import ChatConfig
from nous.infrastructure.llm.base import DoneEvent, TextDeltaEvent, ToolCallEvent

_CHAT_JS_PATH = (
    Path(__file__).resolve().parent.parent.parent / "nous" / "api" / "http" / "static" / "chat" / "chat-core.js"
)


def _read_chat_js() -> str:
    """Read the extracted chat.js static file (formerly inline in render_chat_js)."""
    return _CHAT_JS_PATH.read_text(encoding="utf-8")


# ─────────────────────────────────────────────────────────────
# TreeSessionWindow tests (migrated from SessionWindow)
# ─────────────────────────────────────────────────────────────


class TestTreeSessionWindow:
    def test_initial_empty(self):
        win = TreeSessionWindow(max_messages=6)
        assert len(win) == 0

    def test_add_and_retrieve(self):
        win = TreeSessionWindow(max_messages=4)
        win.add("user", "hello")
        win.add("assistant", "hi there")
        assert len(win) == 2

    def test_max_messages_eviction(self):
        win = TreeSessionWindow(max_messages=4)
        for i in range(6):
            win.add("user" if i % 2 == 0 else "assistant", f"msg{i}")
        assert len(win) == 4

    def test_get_labeled_messages_returns_llm_messages(self):
        win = TreeSessionWindow(max_messages=6)
        ts = datetime(2025, 1, 1, 12, 0, 0)
        win.add("user", "test message", ts)
        now = datetime(2025, 1, 1, 13, 0, 0)
        msgs = win.get_labeled_messages(now)
        assert len(msgs) == 1
        assert msgs[0].role == "user"
        assert msgs[0].content == "test message"
        assert msgs[0].time_label == "1h ago"

    def test_labeled_messages_recent(self):
        win = TreeSessionWindow(max_messages=6)
        now = datetime(2025, 3, 1, 10, 0, 0)
        win.add("user", "just now message", now)
        msgs = win.get_labeled_messages(now)
        assert msgs[0].time_label == "just now"

    def test_flush_persists_to_sqlite_immediately(self):
        """flush() forces DB write even when batch_size not reached."""
        import json
        import sqlite3

        db = sqlite3.connect(":memory:")
        db.execute("""
            CREATE TABLE IF NOT EXISTS chat_sessions (
                persona TEXT NOT NULL, session_id TEXT NOT NULL,
                messages TEXT NOT NULL DEFAULT '[]', timestamps TEXT NOT NULL DEFAULT '[]',
                updated_at TEXT NOT NULL, PRIMARY KEY (persona, session_id))
        """)
        db.commit()

        win = TreeSessionWindow(max_messages=20, batch_size=10)  # batch_size=10 > 1 message
        win.attach_db(db, "test_persona", "test_session")
        win.add("user", "hello")  # 1 message, won't trigger _persist (batch_size=10)

        # Before flush: DB should be empty
        row_before = db.execute(
            "SELECT messages FROM chat_sessions WHERE persona=? AND session_id=?",
            ("test_persona", "test_session"),
        ).fetchone()
        assert row_before is None, "DB should be empty before flush (batch_size not reached)"

        # Act
        win.flush()

        # After flush: DB should have the message
        row_after = db.execute(
            "SELECT messages FROM chat_sessions WHERE persona=? AND session_id=?",
            ("test_persona", "test_session"),
        ).fetchone()
        assert row_after is not None, "DB should have data after flush"
        data = json.loads(row_after[0])
        assert "root_id" in data
        assert "active_leaf_id" in data
        assert "nodes" in data
        assert len(data["nodes"]) == 1
        assert data["nodes"][0]["role"] == "user"
        assert data["nodes"][0]["content"] == "hello"


# ─────────────────────────────────────────────────────────────
# TreeSessionWindow 新機能 tests
# ─────────────────────────────────────────────────────────────


class TestTreeSessionWindowNew:
    """TreeSessionWindow の新機能テスト"""

    def test_add_returns_msg_id(self):
        """add() は UUID 文字列を返す"""
        win = TreeSessionWindow()
        msg_id = win.add("user", "hello")
        assert isinstance(msg_id, str)
        assert len(msg_id) > 30  # UUID

    def test_get_active_path_returns_correct_order(self):
        """get_active_path() は追加順のパスを返す"""
        win = TreeSessionWindow()
        win.add("user", "hello")
        win.add("assistant", "hi")
        path = win.get_active_path()
        assert len(path) == 2
        assert path[0]["role"] == "user"
        assert path[1]["role"] == "assistant"

    def test_edit_message_updates_content(self):
        """edit_message() は content を更新する"""
        win = TreeSessionWindow()
        msg_id = win.add("user", "hello")
        updated = win.edit_message(msg_id, "hello world")
        assert updated is not None
        assert updated["content"] == "hello world"

    def test_edit_message_returns_none_for_unknown_id(self):
        """存在しないIDでは None を返す"""
        win = TreeSessionWindow()
        result = win.edit_message("nonexistent", "test")
        assert result is None

    def test_rollback_to_changes_active_leaf_only(self):
        """rollback_to() は active_leaf_id のみ変更し、ノードは保持する"""
        win = TreeSessionWindow()
        uid = win.add("user", "hello")
        win.add("assistant", "hi")
        result = win.rollback_to(uid)
        assert result is not None
        assert result["new_active_leaf_id"] == uid
        assert len(win.get_active_path()) == 1
        # assistant ノードはまだ存在する
        assert win.get_message_by_id(result["old_active_leaf_id"]) is not None

    def test_get_labeled_messages_uses_active_path(self):
        """get_labeled_messages() は active_path を使う"""
        win = TreeSessionWindow()
        ts = datetime(2025, 1, 1, 12, 0, 0)
        win.add("user", "hello", ts)
        now = datetime(2025, 1, 1, 13, 0, 0)
        msgs = win.get_labeled_messages(now)
        assert len(msgs) == 1
        assert msgs[0].role == "user"
        assert msgs[0].content == "hello"

    def test_flush_persists_tree_format(self):
        """flush() で新JSON形式（root_id, active_leaf_id, nodes）が保存される"""
        import json
        import sqlite3

        db = sqlite3.connect(":memory:")
        db.execute("""
            CREATE TABLE IF NOT EXISTS chat_sessions (
                persona TEXT NOT NULL, session_id TEXT NOT NULL,
                messages TEXT NOT NULL DEFAULT '[]',
                timestamps TEXT NOT NULL DEFAULT '[]',
                updated_at TEXT NOT NULL,
                PRIMARY KEY (persona, session_id))
        """)
        db.commit()
        win = TreeSessionWindow(max_messages=20, batch_size=100)
        win.attach_db(db, "test", "s1")
        win.add("user", "hello")
        win.flush()
        row = db.execute(
            "SELECT messages FROM chat_sessions WHERE persona=? AND session_id=?",
            ("test", "s1"),
        ).fetchone()
        assert row is not None
        data = json.loads(row[0])
        assert "root_id" in data
        assert "active_leaf_id" in data
        assert "nodes" in data

    def test_from_db_migrates_old_flat_format(self):
        """旧フラット配列形式を from_db() が自動マイグレーションする"""
        import json
        import sqlite3

        db = sqlite3.connect(":memory:")
        db.execute("""
            CREATE TABLE IF NOT EXISTS chat_sessions (
                persona TEXT NOT NULL, session_id TEXT NOT NULL,
                messages TEXT NOT NULL DEFAULT '[]',
                timestamps TEXT NOT NULL DEFAULT '[]',
                updated_at TEXT NOT NULL,
                PRIMARY KEY (persona, session_id))
        """)
        db.commit()
        # 旧形式データ
        old_messages = json.dumps([{"role": "user", "content": "hello"}, {"role": "assistant", "content": "hi"}])
        old_timestamps = json.dumps(["2025-01-01T12:00:00", "2025-01-01T12:01:00"])
        db.execute(
            "INSERT INTO chat_sessions VALUES (?, ?, ?, ?, ?)",
            ("test", "s1", old_messages, old_timestamps, "2025-01-01T12:00:00"),
        )
        db.commit()

        win = TreeSessionWindow.from_db(db, "test", "s1")
        assert win is not None
        path = win.get_active_path()
        assert len(path) == 2
        # 全ノードが UUID を持つ
        for node in path:
            assert "id" in node
            assert len(node["id"]) > 30
        # parent_id がチェーンされている
        assert path[0]["parent_id"] is None
        assert path[1]["parent_id"] == path[0]["id"]

    def test_max_messages_eviction(self):
        """max_messages 超過時に古いノードが evict される"""
        win = TreeSessionWindow(max_messages=4)
        for i in range(6):
            win.add("user" if i % 2 == 0 else "assistant", f"msg{i}")
        assert win.get_message_count() <= 4

    # ── Bug #3: segments 編集対応 ─────────────────────────────

    def test_edit_message_updates_segments_text(self):
        """edit_message() は text セグメントの content も更新する"""
        win = TreeSessionWindow()
        segments = [
            {"type": "tool_call", "name": "search", "input": {"q": "test"}},
            {"type": "text", "content": "old result"},
        ]
        msg_id = win.add("assistant", "old result", segments=segments)
        updated = win.edit_message(msg_id, "new result")
        assert updated is not None
        assert updated["content"] == "new result"
        # segments 内の text も更新されている
        segs = updated.get("segments", [])
        text_segs = [s for s in segs if s.get("type") == "text"]
        assert len(text_segs) == 1
        assert text_segs[0]["content"] == "new result"
        # tool_call セグメントは更新されていない
        tool_segs = [s for s in segs if s.get("type") == "tool_call"]
        assert tool_segs[0]["input"]["q"] == "test"

    def test_edit_message_no_segments_still_works(self):
        """segments なし edit_message() は従来通り動作する"""
        win = TreeSessionWindow()
        msg_id = win.add("user", "hello")
        updated = win.edit_message(msg_id, "world")
        assert updated is not None
        assert updated["content"] == "world"
        assert "segments" not in updated

    def test_edit_message_segments_no_text_type(self):
        """text タイプがない segments では content のみ更新される"""
        win = TreeSessionWindow()
        segments = [{"type": "tool_call", "name": "search", "input": {}}]
        msg_id = win.add("assistant", "result", segments=segments)
        updated = win.edit_message(msg_id, "new result")
        assert updated["content"] == "new result"
        segs = updated.get("segments", [])
        text_segs = [s for s in segs if s.get("type") == "text"]
        assert len(text_segs) == 0  # text がないので変わらない

    # ── Bug #4: 楽観的ロック ──────────────────────────────────

    def test_version_starts_at_zero(self):
        win = TreeSessionWindow()
        assert win.get_version() == 0

    def test_version_increments_on_edit(self):
        win = TreeSessionWindow()
        msg_id = win.add("user", "hello")
        v1 = win.get_version()
        win.edit_message(msg_id, "world")
        assert win.get_version() == v1 + 1

    def test_version_increments_on_delete(self):
        win = TreeSessionWindow()
        aid = win.add("assistant", "msg")
        v1 = win.get_version()
        win.delete_message(aid)
        assert win.get_version() == v1 + 1

    def test_version_increments_on_rollback(self):
        win = TreeSessionWindow()
        uid = win.add("user", "hello")
        win.add("assistant", "hi")
        v1 = win.get_version()
        win.rollback_to(uid)
        assert win.get_version() == v1 + 1

    def test_version_persisted_and_restored(self):
        """version は永続化され、from_db() で復元される"""
        import sqlite3

        db = sqlite3.connect(":memory:")
        db.execute("""
            CREATE TABLE IF NOT EXISTS chat_sessions (
                persona TEXT NOT NULL, session_id TEXT NOT NULL,
                messages TEXT NOT NULL DEFAULT '[]',
                timestamps TEXT NOT NULL DEFAULT '[]',
                updated_at TEXT NOT NULL,
                PRIMARY KEY (persona, session_id))
        """)
        db.commit()

        win = TreeSessionWindow()
        win.attach_db(db, "test", "s1")
        win.add("user", "hello")
        win.edit_message(list(win._nodes.keys())[0], "world")  # version → 1
        win.delete_message(list(win._nodes.keys())[0])  # version → 2 (全部消える)
        win.add("user", "again")
        v_saved = win.get_version()
        win.flush()

        loaded = TreeSessionWindow.from_db(db, "test", "s1")
        assert loaded is not None
        assert loaded.get_version() == v_saved

    def test_old_data_without_version_gets_zero(self):
        """version がない旧データは from_db() で version=0 になる"""
        import json
        import sqlite3

        db = sqlite3.connect(":memory:")
        db.execute("""
            CREATE TABLE IF NOT EXISTS chat_sessions (
                persona TEXT NOT NULL, session_id TEXT NOT NULL,
                messages TEXT NOT NULL DEFAULT '[]',
                timestamps TEXT NOT NULL DEFAULT '[]',
                updated_at TEXT NOT NULL,
                PRIMARY KEY (persona, session_id))
        """)
        db.commit()

        # version なしの新形式データ
        data = {
            "root_id": None,
            "active_leaf_id": None,
            "nodes": [],
        }
        db.execute(
            "INSERT INTO chat_sessions VALUES (?, ?, ?, ?, ?)",
            ("test", "s1", json.dumps(data), "[]", "2025-01-01T12:00:00"),
        )
        db.commit()

        loaded = TreeSessionWindow.from_db(db, "test", "s1")
        assert loaded is not None
        assert loaded.get_version() == 0


# ─────────────────────────────────────────────────────────────
# SessionManager tests
# ─────────────────────────────────────────────────────────────


class TestSessionManager:
    def test_creates_new_session(self):
        mgr = SessionManager(max_sessions=10)
        win = mgr.get_or_create("persona1", "session1", max_messages=6)
        assert isinstance(win, TreeSessionWindow)

    def test_returns_same_session(self):
        mgr = SessionManager(max_sessions=10)
        win1 = mgr.get_or_create("persona1", "session1")
        win2 = mgr.get_or_create("persona1", "session1")
        assert win1 is win2

    def test_different_persona_different_session(self):
        mgr = SessionManager(max_sessions=10)
        win1 = mgr.get_or_create("persona1", "session1")
        win2 = mgr.get_or_create("persona2", "session1")
        assert win1 is not win2

    def test_lru_eviction(self):
        mgr = SessionManager(max_sessions=2)
        mgr.get_or_create("p1", "s1")
        mgr.get_or_create("p2", "s2")
        mgr.get_or_create("p3", "s3")  # p1/s1 should be evicted
        assert ("p1", "s1") not in mgr._sessions
        assert ("p2", "s2") in mgr._sessions
        assert ("p3", "s3") in mgr._sessions

    def test_clear_removes_session(self):
        mgr = SessionManager(max_sessions=10)
        mgr.get_or_create("p1", "s1")
        mgr.clear("p1", "s1")
        assert ("p1", "s1") not in mgr._sessions

    def test_clear_nonexistent_is_noop(self):
        mgr = SessionManager(max_sessions=10)
        mgr.clear("nonexistent", "session")  # should not raise


# ─────────────────────────────────────────────────────────────
# ChatConfig tests
# ─────────────────────────────────────────────────────────────


class TestChatConfig:
    def test_defaults(self):
        cfg = ChatConfig(persona="test")
        assert cfg.provider == "anthropic"
        assert cfg.model == ""
        assert cfg.temperature == 0.7
        assert cfg.max_tokens == 8192

    def test_temperature_clamped(self):
        cfg = ChatConfig(persona="test", temperature=5.0)
        assert cfg.temperature == 2.0
        cfg2 = ChatConfig(persona="test", temperature=-1.0)
        assert cfg2.temperature == 0.0

    def test_max_tokens_clamped(self):
        cfg = ChatConfig(persona="test", max_tokens=99999)
        assert cfg.max_tokens == 32768
        cfg2 = ChatConfig(persona="test", max_tokens=0)
        assert cfg2.max_tokens == 1

    def test_tool_calls_clamped(self):
        cfg = ChatConfig(persona="test", max_tool_calls=50)
        assert cfg.max_tool_calls == 20

    def test_get_effective_model_default(self):
        cfg = ChatConfig(persona="test", provider="anthropic", model="")
        assert cfg.get_effective_model() == "claude-opus-4-5"

    def test_get_effective_model_custom(self):
        cfg = ChatConfig(persona="test", provider="anthropic", model="claude-3-haiku-20240307")
        assert cfg.get_effective_model() == "claude-3-haiku-20240307"

    def test_get_effective_base_url_openrouter(self):
        cfg = ChatConfig(persona="test", provider="openrouter", base_url="")
        assert cfg.get_effective_base_url() == "https://openrouter.ai/api/v1"

    def test_get_effective_api_key_stored(self):
        cfg = ChatConfig(persona="test", api_key="sk-abc123")
        assert cfg.get_effective_api_key() == "sk-abc123"

    def test_get_effective_api_key_from_env(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "env-key-123")
        cfg = ChatConfig(persona="test", provider="anthropic", api_key=None)
        assert cfg.get_effective_api_key() == "env-key-123"

    def test_is_configured_with_key(self):
        cfg = ChatConfig(persona="test", api_key="sk-test")
        assert cfg.is_configured() is True

    def test_is_not_configured_without_key(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        cfg = ChatConfig(persona="test", api_key="")
        assert cfg.is_configured() is False

    def test_to_safe_dict_masks_key(self):
        cfg = ChatConfig(persona="test", api_key="sk-secret-key-12345")
        d = cfg.to_safe_dict()
        assert "secret" not in d["api_key"]
        assert d["api_key"].endswith("****")
        assert d["is_configured"] is True

    def test_to_safe_dict_empty_key(self):
        cfg = ChatConfig(persona="test", api_key="")
        d = cfg.to_safe_dict()
        assert d["api_key"] == ""
        assert d["is_configured"] is False

    # ── Dynamic temperature + top_p (TA02) ──

    def test_dynamic_temperature_default(self):
        cfg = ChatConfig(persona="test")
        assert cfg.dynamic_temperature is True

    def test_emotion_temperature_scale_default(self):
        cfg = ChatConfig(persona="test")
        assert cfg.emotion_temperature_scale == 0.2

    def test_emotion_temperature_scale_clamped(self):
        cfg = ChatConfig(persona="test", emotion_temperature_scale=2.0)
        assert cfg.emotion_temperature_scale == 1.0
        cfg2 = ChatConfig(persona="test", emotion_temperature_scale=-0.5)
        assert cfg2.emotion_temperature_scale == 0.0

    def test_top_p_default_none(self):
        cfg = ChatConfig(persona="test")
        assert cfg.top_p is None

    def test_top_p_clamped_low(self):
        cfg = ChatConfig(persona="test", top_p=0.0)
        assert cfg.top_p == 0.0  # 境界: 0.0 は許可

    def test_top_p_clamped_high(self):
        cfg = ChatConfig(persona="test", top_p=1.5)
        assert cfg.top_p == 1.0

    def test_top_p_negative(self):
        cfg = ChatConfig(persona="test", top_p=-1.0)
        assert cfg.top_p == 0.0  # clamp to (0.0, 1.0]

    def test_top_p_accepted_value(self):
        cfg = ChatConfig(persona="test", top_p=0.9)
        assert cfg.top_p == 0.9


# ─────────────────────────────────────────────────────────────
# _sse helper tests
# ─────────────────────────────────────────────────────────────


class TestSseHelper:
    def test_format(self):
        result = _sse("text_delta", {"content": "hello"})
        assert result.startswith("data: ")
        assert result.endswith("\n\n")

    def test_json_content(self):
        import json

        result = _sse("done", {"message": "completed"})
        payload = json.loads(result[6:].strip())
        assert payload["type"] == "done"
        assert payload["message"] == "completed"

    def test_unicode_preserved(self):
        result = _sse("text_delta", {"content": "日本語テスト"})
        assert "日本語テスト" in result


# ─────────────────────────────────────────────────────────────
# ChatService basic tests (with mocked LLM provider)
# ─────────────────────────────────────────────────────────────


class TestChatService:
    def _make_ctx(self):
        """Build a minimal mock AppContext."""
        ctx = MagicMock()
        ctx.persona = "test_persona"

        # event_bus (must be async mocks for ChatService event publishing)
        ctx.event_bus = MagicMock()
        ctx.event_bus.publish = AsyncMock()

        # persona_service
        state = MagicMock()
        state.emotion = "neutral"
        state.emotion_intensity = 0.5
        state.mental_state = None
        state.physical_state = None
        state.environment = None
        state.fatigue = None
        state.warmth = None
        state.arousal = None
        state.last_conversation_time = None
        state.heart_rate = None
        state.pain = None
        state_result = MagicMock()
        state_result.is_ok = True
        state_result.value = state
        ctx.persona_service.get_context.return_value = state_result

        # search_engine
        search_result = MagicMock()
        search_result.is_ok = True
        search_result.value = []
        ctx.search_engine.search.return_value = search_result

        return ctx

    def _make_config(self, api_key="test-key"):
        return ChatConfig(
            persona="test_persona",
            provider="anthropic",
            api_key=api_key,
            model="claude-opus-4-5",
        )

    @pytest.mark.asyncio
    async def test_no_api_key_yields_error(self):
        from nous.application.chat_service import ChatService

        ctx = self._make_ctx()
        cfg = self._make_config(api_key="")
        service = ChatService()
        chunks = []
        async for chunk in service.chat(ctx, cfg, "sess1", "hello"):
            chunks.append(chunk)
        import json

        assert any("error" in chunk for chunk in chunks)
        # Skip non-data SSE events (heartbeat comments ": ...")
        data_chunks = [c for c in chunks if c.startswith("data: ")]
        payload = json.loads(data_chunks[0][6:].strip())
        assert payload["type"] == "error"
        assert "APIキー" in payload["message"]

    @pytest.mark.asyncio
    async def test_top_p_passed_to_provider_stream(self):
        """Verify top_p from ChatConfig is forwarded to provider.stream()."""
        from nous.application.chat_service import ChatService

        captured_kwargs = {}

        async def mock_stream(*args, **kwargs):
            captured_kwargs.update(kwargs)
            yield TextDeltaEvent(content="ok")
            yield DoneEvent(full_content="ok", tool_calls=[])

        mock_provider = MagicMock()
        mock_provider.stream = mock_stream

        ctx = self._make_ctx()
        cfg = self._make_config(api_key="sk-valid-key")
        cfg.top_p = 0.9
        service = ChatService()

        with patch("nous.application.chat.pipeline.inference.get_provider", return_value=mock_provider):
            async for _ in service.chat(ctx, cfg, "sess1", "hello"):
                pass

        assert captured_kwargs.get("top_p") == 0.9

    @pytest.mark.asyncio
    async def test_top_p_none_in_kwargs_when_config_none(self):
        """When top_p is None in ChatConfig, provider.stream() receives top_p=None."""
        from nous.application.chat_service import ChatService

        captured_kwargs = {}

        async def mock_stream(*args, **kwargs):
            captured_kwargs.update(kwargs)
            yield TextDeltaEvent(content="ok")
            yield DoneEvent(full_content="ok", tool_calls=[])

        mock_provider = MagicMock()
        mock_provider.stream = mock_stream

        ctx = self._make_ctx()
        cfg = self._make_config(api_key="sk-valid-key")
        cfg.top_p = None  # default
        service = ChatService()

        with patch("nous.application.chat.pipeline.inference.get_provider", return_value=mock_provider):
            async for _ in service.chat(ctx, cfg, "sess1", "hello"):
                pass

        # top_p is always passed to provider.stream(); provider filters None → not sent to API
        assert "top_p" in captured_kwargs
        assert captured_kwargs["top_p"] is None

    @pytest.mark.asyncio
    async def test_reasoning_effort_passed_when_enabled(self):
        """reasoning_enabled=True → provider.stream() に reasoning_effort が伝播."""
        from nous.application.chat_service import ChatService

        captured_kwargs = {}

        async def mock_stream(*args, **kwargs):
            captured_kwargs.update(kwargs)
            yield TextDeltaEvent(content="ok")
            yield DoneEvent(full_content="ok", tool_calls=[])

        mock_provider = MagicMock()
        mock_provider.stream = mock_stream

        ctx = self._make_ctx()
        cfg = self._make_config(api_key="sk-valid-key")
        cfg.reasoning_enabled = True
        cfg.reasoning_effort = "high"
        service = ChatService()

        with patch("nous.application.chat.pipeline.inference.get_provider", return_value=mock_provider):
            async for _ in service.chat(ctx, cfg, "sess1", "hello"):
                pass

        assert captured_kwargs.get("reasoning_effort") == "high"

    @pytest.mark.asyncio
    async def test_reasoning_effort_none_when_disabled(self):
        """reasoning_enabled=False → reasoning_effort=None（config に effort 設定があっても）."""
        from nous.application.chat_service import ChatService

        captured_kwargs = {}

        async def mock_stream(*args, **kwargs):
            captured_kwargs.update(kwargs)
            yield TextDeltaEvent(content="ok")
            yield DoneEvent(full_content="ok", tool_calls=[])

        mock_provider = MagicMock()
        mock_provider.stream = mock_stream

        ctx = self._make_ctx()
        cfg = self._make_config(api_key="sk-valid-key")
        cfg.reasoning_enabled = False
        cfg.reasoning_effort = "max"  # 無効時は設定されていても None になる
        service = ChatService()

        with patch("nous.application.chat.pipeline.inference.get_provider", return_value=mock_provider):
            async for _ in service.chat(ctx, cfg, "sess1", "hello"):
                pass

        assert "reasoning_effort" in captured_kwargs
        assert captured_kwargs["reasoning_effort"] is None

    @pytest.mark.asyncio
    async def test_thinking_not_mixed_into_full_response(self):
        """CoT が full_response（保存される assistant テキスト）に混入しない (SPEC R10d)."""
        import json

        from nous.application.chat_service import ChatService
        from nous.infrastructure.llm.base import ThinkingDeltaEvent

        async def mock_stream(*args, **kwargs):
            yield ThinkingDeltaEvent(content="secret chain of thought")
            yield TextDeltaEvent(content="public answer")
            yield DoneEvent(full_content="public answer", tool_calls=[])

        mock_provider = MagicMock()
        mock_provider.stream = mock_stream

        ctx = self._make_ctx()
        cfg = self._make_config(api_key="sk-valid-key")
        service = ChatService()

        mock_session = MagicMock()
        with (
            patch("nous.application.chat.pipeline.inference.get_provider", return_value=mock_provider),
            patch("nous.application.chat.service._session_manager.get_or_create", return_value=mock_session),
        ):
            chunks = []
            async for chunk in service.chat(ctx, cfg, "sess1", "hello"):
                chunks.append(chunk)

        # ThinkingDeltaSSE は配信される（フロント表示用）
        data_chunks = [c for c in chunks if c.startswith("data: ")]
        types = [json.loads(c[6:].strip())["type"] for c in data_chunks]
        assert "thinking_delta" in types
        thinking_payloads = [
            json.loads(c[6:].strip()) for c in data_chunks if json.loads(c[6:].strip())["type"] == "thinking_delta"
        ]
        assert any(p.get("content") == "secret chain of thought" for p in thinking_payloads)

        # full_response には thinking が混入しない
        assistant_calls = [c for c in mock_session.add.call_args_list if c.args[0] == "assistant"]
        assert assistant_calls, "assistant メッセージの保存呼び出しが存在すること"
        content = assistant_calls[0].args[1]
        assert content == "public answer"
        assert "secret chain of thought" not in content

        # segments には thinking が保存される
        segments = assistant_calls[0].kwargs.get("segments") or []
        assert any(s.get("type") == "thinking" and s.get("content") == "secret chain of thought" for s in segments)

    @pytest.mark.asyncio
    async def test_streams_text_and_done(self):
        from nous.application.chat_service import ChatService

        async def mock_stream(*args, **kwargs):
            yield TextDeltaEvent(content="Hello ")
            yield TextDeltaEvent(content="world!")
            yield DoneEvent(full_content="Hello world!", tool_calls=[])

        mock_provider = MagicMock()
        mock_provider.stream = mock_stream

        ctx = self._make_ctx()
        cfg = self._make_config(api_key="sk-valid-key")
        service = ChatService()

        with patch("nous.application.chat.pipeline.inference.get_provider", return_value=mock_provider):
            chunks = []
            async for chunk in service.chat(ctx, cfg, "sess1", "hello"):
                chunks.append(chunk)

        import json

        # Skip non-data SSE events (heartbeat comments ": ...")
        data_chunks = [c for c in chunks if c.startswith("data: ")]
        types = [json.loads(c[6:].strip())["type"] for c in data_chunks]
        assert "text_delta" in types
        assert "done" in types

    @pytest.mark.asyncio
    async def test_tool_call_executed(self):
        from nous.application.chat_service import ChatService

        tool_evt = ToolCallEvent(
            tool_name="memory_search",
            tool_input={"query": "test"},
            tool_use_id="tool_001",
        )

        call_count = 0

        async def mock_stream(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                yield tool_evt
                yield DoneEvent(full_content="", tool_calls=[tool_evt])
            else:
                yield TextDeltaEvent(content="Found it!")
                yield DoneEvent(full_content="Found it!", tool_calls=[])

        mock_provider = MagicMock()
        mock_provider.stream = mock_stream

        ctx = self._make_ctx()
        # Make search return something
        from nous.domain.memory.entities import Memory
        from nous.domain.search.engine import SearchResult

        mem = Memory(
            key="mem_001",
            content="test memory",
            created_at=datetime(2025, 1, 1, 12, 0, 0),
            updated_at=datetime(2025, 1, 1, 12, 0, 0),
            importance=0.8,
            emotion="neutral",
        )
        search_result = MagicMock()
        search_result.is_ok = True
        search_result.value = [SearchResult(memory=mem, score=0.9, source="keyword")]
        ctx.search_engine.search.return_value = search_result

        cfg = self._make_config(api_key="sk-valid-key")
        service = ChatService()

        with patch("nous.application.chat.pipeline.inference.get_provider", return_value=mock_provider):
            chunks = []
            async for chunk in service.chat(ctx, cfg, "sess2", "search memories"):
                chunks.append(chunk)

        import json

        # Skip non-data SSE events (heartbeat comments ": ...")
        data_chunks = [c for c in chunks if c.startswith("data: ")]
        types = [json.loads(c[6:].strip())["type"] for c in data_chunks]
        assert "tool_call" in types
        assert "tool_result" in types
        assert "done" in types


# ─────────────────────────────────────────────────────────────
# max_stored_messages truncation path highlights (§4.2)
# ─────────────────────────────────────────────────────────────


class TestMaxStoredMessagesHighlights:
    """keep_recent_turns=0 構成で第2切り詰め経路（max_stored_messages スライス）発火時、
    ハイライトが system セクション <conversation_history_summary> に現れること。"""

    def _make_ctx(self):
        ctx = MagicMock()
        ctx.persona = "test_persona"
        ctx.event_bus = MagicMock()
        ctx.event_bus.publish = AsyncMock()
        state = MagicMock()
        state.emotion = "neutral"
        state.emotion_intensity = 0.5
        state.mental_state = None
        state.physical_state = None
        state.environment = None
        state.fatigue = None
        state.warmth = None
        state.arousal = None
        state.last_conversation_time = None
        state.heart_rate = None
        state.pain = None
        state_result = MagicMock()
        state_result.is_ok = True
        state_result.value = state
        ctx.persona_service.get_context.return_value = state_result
        search_result = MagicMock()
        search_result.is_ok = True
        search_result.value = []
        ctx.search_engine.search.return_value = search_result
        return ctx

    @pytest.mark.asyncio
    async def test_max_stored_messages_path_injects_highlights(self):
        from nous.application.chat_service import ChatService
        from nous.infrastructure.llm.base import LLMMessage

        async def mock_stream(*args, **kwargs):
            yield TextDeltaEvent(content="ok")
            yield DoneEvent(full_content="ok", tool_calls=[])

        mock_provider = MagicMock()
        mock_provider.stream = mock_stream

        ctx = self._make_ctx()
        cfg = ChatConfig(
            persona="test_persona",
            provider="anthropic",
            api_key="sk-valid-key",
            model="claude-opus-4-5",
        )
        cfg.context_keep_recent_turns = 0  # Stage 0 無効 → 第2経路が唯一の切り詰め
        cfg.max_stored_messages = 4
        cfg.context_use_llm_summary = False

        session_msgs: list[LLMMessage] = []
        for i in range(6):
            session_msgs.append(LLMMessage(role="user", content=f"user question {i}"))
            session_msgs.append(LLMMessage(role="assistant", content=f"assistant answer {i}"))

        mock_session = MagicMock()
        mock_session.get_labeled_messages.return_value = session_msgs

        captured: dict = {}

        def _capture_prompt_build(ctx, config, turn_ctx):
            turn_ctx.system_prompt = "base sys\n<!-- __STATIC_END__ -->"
            captured["turn_ctx"] = turn_ctx

        service = ChatService()
        with (
            patch("nous.application.chat.pipeline.inference.get_provider", return_value=mock_provider),
            patch("nous.application.chat.service._session_manager.get_or_create", return_value=mock_session),
            patch("nous.application.chat.service.PromptBuildStep") as mock_pbs,
        ):
            mock_pbs.return_value.run.side_effect = _capture_prompt_build
            async for _ in service.chat(ctx, cfg, "sess-highlights", "hello"):
                pass

        assert "turn_ctx" in captured
        system_prompt = captured["turn_ctx"].system_prompt
        # ハイライトが system に現れる（メッセージ偽装ではなく）
        assert "<conversation_history_summary>" in system_prompt
        assert "[0] user: user question 0" in system_prompt
        assert "[7] assistant: assistant answer 3" in system_prompt
        # 先頭3 + 末尾3（[3]〜[4] は落ちる）
        hl_block = system_prompt.split("<conversation_history_summary>", 1)[1].split(
            "</conversation_history_summary>", 1
        )[0]
        assert "[3]" not in hl_block
        assert "[4]" not in hl_block
        # キャッシュ境界の後ろ（動的領域）に注入される
        assert system_prompt.index("<!-- __STATIC_END__ -->") < system_prompt.index("<conversation_history_summary>")


# ─────────────────────────────────────────────────────────────
# Chat tab control tests
# ─────────────────────────────────────────────────────────────


def test_chat_tab_buttons_use_panel_toggle_handlers():
    """Top control buttons route through CSP-safe data-action delegation."""
    html = render_chat_tab()

    assert 'data-action="chat-toggle-memory"' in html
    assert 'data-action="chat-toggle-settings"' in html


def test_chat_tab_renders_all_toggle_panels():
    """Each top-level toggle button should have a corresponding panel in the markup."""
    html = render_chat_tab()

    assert 'id="memory-panel"' in html
    assert 'id="settings-panel"' in html


def test_chat_tab_renders_memory_panel_support_sections():
    """The memory sidebar should expose recent memories and equipment."""
    html = render_chat_tab()

    assert 'id="memory-saved-list"' in html
    assert 'id="memory-equipment-list"' in html


def test_chat_js_has_single_panel_toggle_definitions():
    """Legacy duplicate handlers should not override the panel toggles."""
    js = _read_chat_js()

    assert js.count("function toggleMemoryPanel()") == 1
    assert js.count("function toggleSettingsPanel()") == 1
    assert "memory-panel-toggle-btn" not in js


# ─────────────────────────────────────────────────────────────
# Tool-only turn fallback (empty text + tool calls → non-empty save)
# ─────────────────────────────────────────────────────────────


class TestToolOnlyFallback:
    def _make_ctx(self):
        ctx = MagicMock()
        ctx.persona = "test_persona"
        ctx.event_bus = MagicMock()
        ctx.event_bus.publish = AsyncMock()
        state = MagicMock()
        state.emotion = "neutral"
        state.emotion_intensity = 0.5
        state.mental_state = None
        state.physical_state = None
        state.environment = None
        state.fatigue = None
        state.warmth = None
        state.arousal = None
        state.last_conversation_time = None
        state.heart_rate = None
        state.pain = None
        state_result = MagicMock()
        state_result.is_ok = True
        state_result.value = state
        ctx.persona_service.get_context.return_value = state_result
        search_result = MagicMock()
        search_result.is_ok = True
        search_result.value = []
        ctx.search_engine.search.return_value = search_result
        return ctx

    def _make_config(self, api_key="sk-valid-key"):
        return ChatConfig(
            persona="test_persona",
            provider="anthropic",
            api_key=api_key,
            model="claude-opus-4-5",
        )

    @pytest.mark.asyncio
    async def test_tool_only_turn_saves_nonempty_fallback(self):
        """空テキスト＋ツール有り → 保存されるassistantテキストが非空になること。"""
        from nous.application.chat_service import ChatService

        tool_evt = ToolCallEvent(
            tool_name="memory_search",
            tool_input={"query": "test"},
            tool_use_id="tool_001",
        )
        call_count = 0

        async def mock_stream(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                yield tool_evt
                yield DoneEvent(full_content="", tool_calls=[tool_evt])
            else:
                yield DoneEvent(full_content="", tool_calls=[])

        mock_provider = MagicMock()
        mock_provider.stream = mock_stream
        ctx = self._make_ctx()
        cfg = self._make_config()
        service = ChatService()
        mock_session = MagicMock()
        with (
            patch("nous.application.chat.pipeline.inference.get_provider", return_value=mock_provider),
            patch("nous.application.chat.service._session_manager.get_or_create", return_value=mock_session),
        ):
            async for _ in service.chat(ctx, cfg, "sess-tool-only", "hello"):
                pass
        assistant_calls = [c for c in mock_session.add.call_args_list if c.args[0] == "assistant"]
        assert assistant_calls, "assistant メッセージの保存呼び出しが存在すること"
        content = assistant_calls[0].args[1]
        assert content != "", "ツールのみターンは空保存してはならない"
        assert "うまく言葉にできなかった" in content

    @pytest.mark.asyncio
    async def test_tool_only_image_turn_uses_tool_message(self):
        """画像生成ツールのみターン → ツール結果のmessageがフォールバック文に使われること。"""
        from unittest.mock import AsyncMock

        from nous.application.chat_service import ChatService

        tool_evt = ToolCallEvent(
            tool_name="image_generate",
            tool_input={"prompt": "a cat"},
            tool_use_id="tool_img_001",
        )
        call_count = 0

        async def mock_stream(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                yield tool_evt
                yield DoneEvent(full_content="", tool_calls=[tool_evt])
            else:
                yield DoneEvent(full_content="", tool_calls=[])

        mock_provider = MagicMock()
        mock_provider.stream = mock_stream
        ctx = self._make_ctx()
        cfg = self._make_config()
        service = ChatService()
        mock_session = MagicMock()
        image_result = {
            "status": "success",
            "message": "Generated 1 image(s)",
            "images": [{"url": "http://x/1.png", "revised_prompt": "a cat"}],
            "provider": "comfyui",
        }
        with (
            patch("nous.application.chat.pipeline.inference.get_provider", return_value=mock_provider),
            patch("nous.application.chat.service._session_manager.get_or_create", return_value=mock_session),
            patch(
                "nous.application.chat.tools.registry.ToolRegistry.execute",
                new=AsyncMock(return_value=image_result),
            ),
        ):
            async for _ in service.chat(ctx, cfg, "sess-tool-img", "draw a cat"):
                pass
        assistant_calls = [c for c in mock_session.add.call_args_list if c.args[0] == "assistant"]
        assert assistant_calls, "assistant メッセージの保存呼び出しが存在すること"
        content = assistant_calls[0].args[1]
        assert content != ""
        assert "Generated 1 image(s)" in content

    @pytest.mark.asyncio
    async def test_nonempty_turn_unchanged(self):
        """full_response非空ターンは一切触らないこと。"""
        from nous.application.chat_service import ChatService

        tool_evt = ToolCallEvent(
            tool_name="memory_search",
            tool_input={"query": "test"},
            tool_use_id="tool_001",
        )
        call_count = 0

        async def mock_stream(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                yield tool_evt
                yield DoneEvent(full_content="", tool_calls=[tool_evt])
            else:
                yield TextDeltaEvent(content="Found it!")
                yield DoneEvent(full_content="Found it!", tool_calls=[])

        mock_provider = MagicMock()
        mock_provider.stream = mock_stream
        ctx = self._make_ctx()
        from datetime import datetime as _dt

        from nous.domain.memory.entities import Memory
        from nous.domain.search.engine import SearchResult

        mem = Memory(
            key="mem_001",
            content="test memory",
            created_at=_dt(2025, 1, 1, 12, 0, 0),
            updated_at=_dt(2025, 1, 1, 12, 0, 0),
            importance=0.8,
            emotion="neutral",
        )
        search_result = MagicMock()
        search_result.is_ok = True
        search_result.value = [SearchResult(memory=mem, score=0.9, source="keyword")]
        ctx.search_engine.search.return_value = search_result
        cfg = self._make_config()
        service = ChatService()
        mock_session = MagicMock()
        with (
            patch("nous.application.chat.pipeline.inference.get_provider", return_value=mock_provider),
            patch("nous.application.chat.service._session_manager.get_or_create", return_value=mock_session),
        ):
            async for _ in service.chat(ctx, cfg, "sess-nonempty", "hello"):
                pass
        assistant_calls = [c for c in mock_session.add.call_args_list if c.args[0] == "assistant"]
        assert assistant_calls, "assistant メッセージの保存呼び出しが存在すること"
        content = assistant_calls[0].args[1]
        assert content == "Found it!"
