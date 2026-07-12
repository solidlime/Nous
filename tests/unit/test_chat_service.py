from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nous.api.http.sections.chat import render_chat_tab
from nous.application.chat.events import _sse_encode as _sse
from nous.application.chat_service import SessionManager, SessionWindow
from nous.domain.chat_config import ChatConfig, ChatConfigRepository
from nous.infrastructure.llm.base import DoneEvent, TextDeltaEvent, ToolCallEvent

_CHAT_JS_PATH = Path(__file__).resolve().parent.parent.parent / "nous" / "api" / "http" / "static" / "chat.js"


def _read_chat_js() -> str:
    """Read the extracted chat.js static file (formerly inline in render_chat_js)."""
    return _CHAT_JS_PATH.read_text(encoding="utf-8")


# ─────────────────────────────────────────────────────────────
# SessionWindow tests
# ─────────────────────────────────────────────────────────────


class TestSessionWindow:
    def test_initial_empty(self):
        win = SessionWindow(max_turns=3)
        assert len(win) == 0

    def test_add_and_retrieve(self):
        win = SessionWindow(max_turns=2)
        win.add("user", "hello")
        win.add("assistant", "hi there")
        assert len(win) == 2

    def test_max_turns_eviction(self):
        win = SessionWindow(max_turns=2)  # max_messages = 4
        for i in range(6):
            win.add("user" if i % 2 == 0 else "assistant", f"msg{i}")
        assert len(win) == 4

    def test_get_labeled_messages_returns_llm_messages(self):
        win = SessionWindow(max_turns=3)
        ts = datetime(2025, 1, 1, 12, 0, 0)
        win.add("user", "test message", ts)
        now = datetime(2025, 1, 1, 13, 0, 0)
        msgs = win.get_labeled_messages(now)
        assert len(msgs) == 1
        assert msgs[0].role == "user"
        assert msgs[0].content == "test message"
        assert msgs[0].time_label == "1h ago"

    def test_labeled_messages_recent(self):
        win = SessionWindow(max_turns=3)
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

        win = SessionWindow(max_turns=10, batch_size=10)  # batch_size=10 > 1 message
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
        messages = json.loads(row_after[0])
        assert len(messages) == 1
        assert messages[0]["role"] == "user"
        assert messages[0]["content"] == "hello"

    def test_update_message_valid_index(self):
        """update_message should update content and persist."""
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

        win = SessionWindow(max_turns=10)
        win.attach_db(db, "test_p", "test_s")
        win.add("user", "original")
        win.add("assistant", "response")

        updated = win.update_message(0, "edited")
        assert updated is not None
        assert updated["role"] == "user"
        assert updated["content"] == "edited"

        # Verify persistence
        row = db.execute(
            "SELECT messages FROM chat_sessions WHERE persona=? AND session_id=?",
            ("test_p", "test_s"),
        ).fetchone()
        msgs = json.loads(row[0])
        assert msgs[0]["content"] == "edited"

    def test_update_message_out_of_range(self):
        win = SessionWindow(max_turns=10)
        win.add("user", "hello")
        assert win.update_message(-1, "x") is None
        assert win.update_message(99, "x") is None

    def test_update_message_preserves_tool_calls(self):
        win = SessionWindow(max_turns=10)
        win.add("assistant", "text", tool_calls=[{"name": "test", "input": {}}])
        updated = win.update_message(0, "new text")
        assert updated is not None
        assert updated["content"] == "new text"
        assert updated["tool_calls"] == [{"name": "test", "input": {}}]


# ─────────────────────────────────────────────────────────────
# SessionManager tests
# ─────────────────────────────────────────────────────────────


class TestSessionManager:
    def test_creates_new_session(self):
        mgr = SessionManager(max_sessions=10)
        win = mgr.get_or_create("persona1", "session1", max_turns=3)
        assert isinstance(win, SessionWindow)

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
        assert cfg.max_tokens == 2048

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

    def test_window_turns_clamped(self):
        cfg = ChatConfig(persona="test", max_window_turns=600)
        assert cfg.max_window_turns == 500
        cfg2 = ChatConfig(persona="test", max_window_turns=0)
        assert cfg2.max_window_turns == 1

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
        cfg = ChatConfig(persona="test", provider="anthropic", api_key="")
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
# ChatConfigRepository tests
# ─────────────────────────────────────────────────────────────


class TestChatConfigRepository:
    def _make_db(self):
        import sqlite3

        db = sqlite3.connect(":memory:")
        db.execute("""
            CREATE TABLE chat_settings (
                persona TEXT PRIMARY KEY,
                provider TEXT DEFAULT 'anthropic',
                model TEXT DEFAULT '',
                api_key TEXT DEFAULT '',
                base_url TEXT DEFAULT '',
                system_prompt TEXT DEFAULT '',
                temperature REAL DEFAULT 0.7,
                max_tokens INTEGER DEFAULT 2048,
                max_window_turns INTEGER DEFAULT 3,
                max_tool_calls INTEGER DEFAULT 5,
                updated_at TEXT,
                auto_extract INTEGER DEFAULT 1,
                extract_model TEXT DEFAULT '',
                extract_max_tokens INTEGER DEFAULT 512,
                tool_result_max_chars INTEGER DEFAULT 4000,
                mcp_servers TEXT DEFAULT '[]',
                enabled_skills TEXT DEFAULT '[]',
                reflection_enabled INTEGER DEFAULT 1,
                reflection_threshold REAL DEFAULT 1.0,
                reflection_min_interval_hours REAL DEFAULT 1.0,
                session_summarize INTEGER DEFAULT 1,
                retrieval_recency_weight REAL DEFAULT 0.3,
                retrieval_importance_weight REAL DEFAULT 0.3,
                retrieval_relevance_weight REAL DEFAULT 0.4,
                retrieval_rrf_k REAL DEFAULT 5.0,
                display_history_turns INTEGER DEFAULT 20,
                housekeeping_threshold INTEGER DEFAULT 10,
                mental_model_enabled INTEGER DEFAULT 1,
                mental_model_min_samples INTEGER DEFAULT 3,
                max_stored_messages INTEGER DEFAULT 200,
                context_max_tokens INTEGER,
                context_compression_threshold REAL DEFAULT 0.8,
                context_compression_mode TEXT DEFAULT 'auto',
                context_keep_recent_turns INTEGER DEFAULT 2,
                context_compress_system_prompt INTEGER DEFAULT 1,
                context_compress_history INTEGER DEFAULT 1,
                memory_preload_count INTEGER DEFAULT 3,
                enable_parallel_tools INTEGER DEFAULT 1,
                image_gen_enabled INTEGER DEFAULT 0,
                image_gen_provider TEXT DEFAULT 'openai',
                image_gen_dalle_model TEXT DEFAULT 'dall-e-3',
                image_gen_stability_url TEXT DEFAULT '',
                image_gen_comfyui_url TEXT DEFAULT '',
                image_gen_gemini_model TEXT DEFAULT 'google/gemini-2.5-flash-image',
                image_gen_replicate_model TEXT DEFAULT 'black-forest-labs/flux-schnell',
                image_gen_replicate_api_key TEXT DEFAULT '',
                dynamic_temperature INTEGER DEFAULT 1,
                emotion_temperature_scale REAL DEFAULT 0.2,
                top_p REAL,
                enable_memory_tools INTEGER DEFAULT 1,
                debug_mode INTEGER DEFAULT 0,
                context_use_llm_summary INTEGER DEFAULT 1,
                episode_consolidation_enabled INTEGER DEFAULT 1,
                episode_search_enabled INTEGER DEFAULT 1,
                dynamic_tool_selection INTEGER DEFAULT 1,
                irodori_enabled INTEGER DEFAULT 0,
                portrait_enabled INTEGER DEFAULT 0,
                voice_auto_play INTEGER DEFAULT 0,
                voice_emotion_link INTEGER DEFAULT 1
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS skills (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                name        TEXT UNIQUE NOT NULL,
                description TEXT DEFAULT '',
                content     TEXT NOT NULL DEFAULT '',
                created_at  TEXT,
                updated_at  TEXT
            )
        """)
        db.commit()
        return db

    def test_get_returns_defaults_when_not_found(self):
        db = self._make_db()
        repo = ChatConfigRepository(db)
        cfg = repo.get("persona1")
        assert cfg.persona == "persona1"
        assert cfg.provider == "anthropic"

    def test_save_and_get(self):
        db = self._make_db()
        repo = ChatConfigRepository(db)
        cfg = ChatConfig(
            persona="persona1",
            provider="openai",
            model="gpt-4o",
            api_key="sk-test",
            temperature=0.5,
        )
        repo.save(cfg)
        loaded = repo.get("persona1")
        assert loaded.provider == "openai"
        assert loaded.model == "gpt-4o"
        assert loaded.api_key == "sk-test"
        assert loaded.temperature == 0.5

    def test_save_updates_existing(self):
        db = self._make_db()
        repo = ChatConfigRepository(db)
        cfg1 = ChatConfig(persona="p1", provider="anthropic", api_key="key1")
        repo.save(cfg1)
        cfg2 = ChatConfig(persona="p1", provider="openai", api_key="key2")
        repo.save(cfg2)
        loaded = repo.get("p1")
        assert loaded.provider == "openai"
        assert loaded.api_key == "key2"

    def test_delete(self):
        db = self._make_db()
        repo = ChatConfigRepository(db)
        cfg = ChatConfig(persona="p1", api_key="sk-abc")
        repo.save(cfg)
        repo.delete("p1")
        loaded = repo.get("p1")
        assert loaded.api_key == ""

    def test_save_and_get_dynamic_temp_top_p(self):
        db = self._make_db()
        repo = ChatConfigRepository(db)
        cfg = ChatConfig(
            persona="p1",
            dynamic_temperature=True,
            emotion_temperature_scale=0.5,
            top_p=0.9,
        )
        repo.save(cfg)
        loaded = repo.get("p1")
        assert loaded.dynamic_temperature is True
        assert loaded.emotion_temperature_scale == 0.5
        assert loaded.top_p == 0.9

    def test_save_and_get_top_p_none(self):
        db = self._make_db()
        repo = ChatConfigRepository(db)
        cfg = ChatConfig(persona="p1")
        assert cfg.top_p is None
        repo.save(cfg)
        loaded = repo.get("p1")
        assert loaded.top_p is None

    def test_get_resilient_to_column_addition(self):
        """get() uses dynamic column mapping: adding a column won't break it."""
        repo = ChatConfigRepository(self._make_db())
        cfg = ChatConfig(
            persona="p1",
            provider="openai",
            model="gpt-4o",
            api_key="sk-test",
            temperature=0.5,
        )
        repo.save(cfg)

        # Simulate schema evolution: add a column
        db = repo._db
        db.execute("ALTER TABLE chat_settings ADD COLUMN dummy_col TEXT DEFAULT 'x'")
        db.commit()

        loaded = repo.get("p1")
        assert loaded.provider == "openai"
        assert loaded.model == "gpt-4o"
        assert loaded.api_key == "sk-test"
        assert loaded.temperature == 0.5
        assert loaded.max_window_turns == 100
        assert loaded.auto_extract is True
        assert loaded.mcp_servers == []

        # Also confirm a newly-inserted row still round-trips
        cfg2 = ChatConfig(persona="p2", provider="anthropic", model="claude-4")
        repo.save(cfg2)
        loaded2 = repo.get("p2")
        assert loaded2.provider == "anthropic"
        assert loaded2.model == "claude-4"


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
        payload = json.loads(chunks[0][6:].strip())
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

        types = [json.loads(c[6:].strip())["type"] for c in chunks]
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

        types = [json.loads(c[6:].strip())["type"] for c in chunks]
        assert "tool_call" in types
        assert "tool_result" in types
        assert "done" in types


# ─────────────────────────────────────────────────────────────
# Chat tab control tests
# ─────────────────────────────────────────────────────────────


def test_chat_tab_buttons_use_panel_toggle_handlers():
    """Top control buttons should call the panel toggle functions directly."""
    html = render_chat_tab()

    assert 'onclick="toggleMemoryPanel()"' in html
    assert 'onclick="toggleSettingsPanel()"' in html


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
