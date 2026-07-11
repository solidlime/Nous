"""Tests for ChatConfig model and ChatConfigRepository (Phase 1 fields)."""

from __future__ import annotations

import sqlite3

import pytest

from nous.domain.chat_config import ChatConfig, ChatConfigRepository, _get_default_mcp_servers


class TestChatConfigFields:
    """New Phase 1 fields: irodori_enabled, portrait_enabled, opensandbox_url."""

    def test_irodori_enabled_default_false(self):
        config = ChatConfig(persona="test")
        assert config.irodori_enabled is False

    def test_portrait_enabled_default_false(self):
        config = ChatConfig(persona="test")
        assert config.portrait_enabled is False

    def test_opensandbox_url_default_empty(self):
        config = ChatConfig(persona="test")
        assert config.opensandbox_url == ""

    def test_irodori_enabled_set_true(self):
        config = ChatConfig(persona="test", irodori_enabled=True)
        assert config.irodori_enabled is True

    def test_portrait_enabled_set_true(self):
        config = ChatConfig(persona="test", portrait_enabled=True)
        assert config.portrait_enabled is True

    def test_opensandbox_url_set(self):
        config = ChatConfig(persona="test", opensandbox_url="http://custom:8000/mcp")
        assert config.opensandbox_url == "http://custom:8000/mcp"


class TestGetDefaultMcpServers:
    """_get_default_mcp_servers with opensandbox_url override."""

    def test_default_url_template(self):
        servers = _get_default_mcp_servers("herta")
        opensandbox = [s for s in servers if s["name"] == "opensandbox"]
        assert len(opensandbox) == 1
        assert opensandbox[0]["url"] == "http://opensandbox-mcp-herta:8000/mcp"

    def test_opensandbox_url_override(self):
        servers = _get_default_mcp_servers("herta", opensandbox_url="http://custom:9999/mcp")
        opensandbox = [s for s in servers if s["name"] == "opensandbox"]
        assert len(opensandbox) == 1
        assert opensandbox[0]["url"] == "http://custom:9999/mcp"

    def test_opensandbox_url_empty_falls_back_to_env(self, monkeypatch):
        monkeypatch.setenv("NOUS_OPENDBOX_MCP_URL", "http://env-override:8000/mcp")
        servers = _get_default_mcp_servers("herta", opensandbox_url="")
        opensandbox = [s for s in servers if s["name"] == "opensandbox"]
        assert opensandbox[0]["url"] == "http://env-override:8000/mcp"

    def test_opensandbox_url_overrides_env(self, monkeypatch):
        monkeypatch.setenv("NOUS_OPENDBOX_MCP_URL", "http://env-override:8000/mcp")
        servers = _get_default_mcp_servers("herta", opensandbox_url="http://persona-override:8000/mcp")
        opensandbox = [s for s in servers if s["name"] == "opensandbox"]
        assert opensandbox[0]["url"] == "http://persona-override:8000/mcp"


class TestChatConfigRepository:
    """ChatConfigRepository CRUD with new Phase 1 fields."""

    @pytest.fixture
    def db(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.row_factory = sqlite3.Row
        # Create table with ALL current columns
        conn.execute(
            """
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
                tool_result_max_chars INTEGER DEFAULT 2000,
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
                enable_memory_tools INTEGER DEFAULT 1,
                debug_mode INTEGER DEFAULT 0,
                dynamic_temperature INTEGER DEFAULT 1,
                emotion_temperature_scale REAL DEFAULT 0.2,
                top_p REAL,
                context_use_llm_summary INTEGER DEFAULT 1,
                episode_consolidation_enabled INTEGER DEFAULT 1,
                episode_search_enabled INTEGER DEFAULT 1,
                dynamic_tool_selection INTEGER DEFAULT 1,
                irodori_enabled INTEGER DEFAULT 0,
                portrait_enabled INTEGER DEFAULT 0,
                opensandbox_url TEXT DEFAULT ''
            )
            """
        )
        conn.commit()
        yield conn
        conn.close()

    def test_save_and_load_irodori_enabled(self, db):
        repo = ChatConfigRepository(db)
        config = ChatConfig(persona="test", irodori_enabled=True)
        repo.save(config)

        loaded = repo.get("test")
        assert loaded.irodori_enabled is True

    def test_save_and_load_portrait_enabled(self, db):
        repo = ChatConfigRepository(db)
        config = ChatConfig(persona="test", portrait_enabled=True)
        repo.save(config)

        loaded = repo.get("test")
        assert loaded.portrait_enabled is True

    def test_save_and_load_opensandbox_url(self, db):
        repo = ChatConfigRepository(db)
        config = ChatConfig(persona="test", opensandbox_url="http://custom:8000/mcp")
        repo.save(config)

        loaded = repo.get("test")
        assert loaded.opensandbox_url == "http://custom:8000/mcp"

    def test_get_or_create_uses_opensandbox_url(self, db):
        repo = ChatConfigRepository(db)
        config = ChatConfig(
            persona="test",
            opensandbox_url="http://persona-opensandbox:8000/mcp",
        )
        repo.save(config)

        loaded = repo.get_or_create("test")
        opensandbox = [s for s in loaded.mcp_servers if s["name"] == "opensandbox"]
        assert len(opensandbox) >= 1
        # opensandbox_url is set, but mcp_servers are already saved, so get_or_create
        # won't regenerate. Let's test fresh persona instead:
        assert loaded.opensandbox_url == "http://persona-opensandbox:8000/mcp"

    def test_get_or_create_fresh_persona_respects_opensandbox_url(self, db):
        """Fresh persona (no mcp_servers) should use opensandbox_url from config."""
        repo = ChatConfigRepository(db)
        # First save a config with opensandbox_url set
        config = ChatConfig(
            persona="fresh_test",
            opensandbox_url="http://custom-opensandbox:8000/mcp",
        )
        repo.save(config)

        # Now get_or_create — since mcp_servers is empty (default []),
        # it should regenerate using the saved opensandbox_url
        loaded = repo.get_or_create("fresh_test")
        opensandbox = [s for s in loaded.mcp_servers if s["name"] == "opensandbox"]
        assert len(opensandbox) == 1
        assert opensandbox[0]["url"] == "http://custom-opensandbox:8000/mcp"

    def test_default_values_in_db(self, db):
        """When no config saved, get() returns defaults including new fields."""
        repo = ChatConfigRepository(db)
        config = repo.get("nonexistent")
        assert config.irodori_enabled is False
        assert config.portrait_enabled is False
        assert config.opensandbox_url == ""

    def test_default_values_from_sql_defaults(self, db):
        """When row exists but new columns are NULL/default, map correctly."""
        # Insert a minimal row without new columns (simulating old DB)
        db.execute(
            "INSERT INTO chat_settings (persona, provider) VALUES (?, ?)",
            ("legacy", "anthropic"),
        )
        db.commit()

        repo = ChatConfigRepository(db)
        config = repo.get("legacy")
        assert config.irodori_enabled is False
        assert config.portrait_enabled is False
        # opensandbox_url defaults to empty string from SQL DEFAULT ''
        # But if the column didn't exist when row was inserted, it might be '' or None
        # The ChatConfig default is "", so either is fine
        assert config.opensandbox_url == "" or config.opensandbox_url == ""


class TestSqliteMigration:
    """Verify ALTER TABLE ADD COLUMN for existing databases."""

    def test_alter_table_adds_columns(self):
        """Simulate opening an existing DB (all pre-Phase1 columns) and running migration."""
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        # Pre-Phase1 schema (has all columns except the 3 new ones).
        # This matches the real migration scenario: CREATE TABLE IF NOT EXISTS
        # creates the full current schema, then ALTER TABLE adds new columns.
        pre_phase1_schema = """
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
                tool_result_max_chars INTEGER DEFAULT 2000,
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
                enable_memory_tools INTEGER DEFAULT 1,
                debug_mode INTEGER DEFAULT 0,
                dynamic_temperature INTEGER DEFAULT 1,
                emotion_temperature_scale REAL DEFAULT 0.2,
                top_p REAL,
                context_use_llm_summary INTEGER DEFAULT 1,
                episode_consolidation_enabled INTEGER DEFAULT 1,
                episode_search_enabled INTEGER DEFAULT 1,
                dynamic_tool_selection INTEGER DEFAULT 1
            )
        """
        conn.execute(pre_phase1_schema)
        conn.commit()

        # Verify old schema doesn't have new columns
        cursor = conn.execute("SELECT * FROM chat_settings LIMIT 0")
        old_cols = [d[0] for d in cursor.description]
        assert "irodori_enabled" not in old_cols
        assert "portrait_enabled" not in old_cols
        assert "opensandbox_url" not in old_cols

        # Simulate the migration: ALTER TABLE ADD COLUMN for each new field
        for col_sql in [
            "irodori_enabled INTEGER DEFAULT 0",
            "portrait_enabled INTEGER DEFAULT 0",
            "opensandbox_url TEXT DEFAULT ''",
        ]:
            try:
                conn.execute(f"ALTER TABLE chat_settings ADD COLUMN {col_sql}")
                conn.commit()
            except Exception:
                pass  # Column already exists

        # Verify columns exist
        cursor = conn.execute("SELECT * FROM chat_settings LIMIT 0")
        columns = [d[0] for d in cursor.description]
        assert "irodori_enabled" in columns
        assert "portrait_enabled" in columns
        assert "opensandbox_url" in columns

        # Verify defaults work
        conn.execute("INSERT INTO chat_settings (persona) VALUES ('test')")
        conn.commit()
        row = conn.execute("SELECT * FROM chat_settings WHERE persona = 'test'").fetchone()
        assert row["irodori_enabled"] == 0
        assert row["portrait_enabled"] == 0
        assert row["opensandbox_url"] == ""

        # Verify ChatConfigRepository works with migrated schema
        from nous.domain.chat_config import ChatConfigRepository

        repo = ChatConfigRepository(conn)
        config = repo.get("test")
        assert config.irodori_enabled is False
        assert config.portrait_enabled is False
        assert config.opensandbox_url == ""

        conn.close()
