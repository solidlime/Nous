"""Tests for ChatConfig model and ChatConfigRepository (Phase 1 fields)."""

from __future__ import annotations

import sqlite3

import pytest

from nous.domain.chat_config import ChatConfig, ChatConfigRepository


class TestChatConfigFields:
    """New Phase 1 fields: irodori_enabled, portrait_enabled."""

    def test_irodori_enabled_default_false(self):
        config = ChatConfig(persona="test")
        assert config.irodori_enabled is False

    def test_portrait_enabled_default_false(self):
        config = ChatConfig(persona="test")
        assert config.portrait_enabled is False

    def test_irodori_enabled_set_true(self):
        config = ChatConfig(persona="test", irodori_enabled=True)
        assert config.irodori_enabled is True

    def test_portrait_enabled_set_true(self):
        config = ChatConfig(persona="test", portrait_enabled=True)
        assert config.portrait_enabled is True


class TestChatConfigRepository:
    """ChatConfigRepository CRUD with new Phase 1 fields."""

    @pytest.fixture
    def db(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.row_factory = sqlite3.Row
        # Create table with ALL current columns (without searxng_url/opensandbox_url)
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
                image_gen_comfyui_url TEXT DEFAULT '',
                image_gen_gemini_model TEXT DEFAULT 'google/gemini-2.5-flash-image',
                image_gen_replicate_model TEXT DEFAULT 'black-forest-labs/flux-schnell',
                image_gen_replicate_api_key TEXT DEFAULT '',
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
                voice_auto_play INTEGER DEFAULT 0,
                voice_emotion_link INTEGER DEFAULT 1,
                disabled_tools TEXT DEFAULT '[]'
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

    def test_get_or_create_empty_servers(self, db):
        """get_or_create should default to empty mcp_servers list."""
        repo = ChatConfigRepository(db)
        config = ChatConfig(persona="test")
        repo.save(config)

        loaded = repo.get_or_create("test")
        assert loaded.mcp_servers == []

    def test_default_values_in_db(self, db):
        """When no config saved, get() returns defaults including new fields."""
        repo = ChatConfigRepository(db)
        config = repo.get("nonexistent")
        assert config.irodori_enabled is False
        assert config.portrait_enabled is False

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


class TestSqliteMigration:
    """Verify ALTER TABLE ADD COLUMN for existing databases."""

    def test_alter_table_adds_columns(self):
        """Simulate opening an existing DB (all pre-Phase1 columns) and running migration."""
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        # Pre-Phase1 schema (has all columns except the 2 new ones).
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
                image_gen_comfyui_url TEXT DEFAULT '',
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

        # Simulate the migration: ALTER TABLE ADD COLUMN for each new field
        for col_sql in [
            "irodori_enabled INTEGER DEFAULT 0",
            "portrait_enabled INTEGER DEFAULT 0",
            "voice_auto_play INTEGER DEFAULT 0",
            "voice_emotion_link INTEGER DEFAULT 1",
            "image_gen_gemini_model TEXT DEFAULT 'google/gemini-2.5-flash-image'",
            "image_gen_replicate_model TEXT DEFAULT 'black-forest-labs/flux-schnell'",
            "image_gen_replicate_api_key TEXT DEFAULT ''",
            "disabled_tools TEXT DEFAULT '[]'",
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
        assert "voice_auto_play" in columns
        assert "voice_emotion_link" in columns
        assert "image_gen_gemini_model" in columns
        assert "image_gen_replicate_model" in columns
        assert "image_gen_replicate_api_key" in columns
        assert "disabled_tools" in columns

        # Verify defaults work
        conn.execute("INSERT INTO chat_settings (persona) VALUES ('test')")
        conn.commit()
        row = conn.execute("SELECT * FROM chat_settings WHERE persona = 'test'").fetchone()
        assert row["irodori_enabled"] == 0
        assert row["portrait_enabled"] == 0
        assert row["voice_auto_play"] == 0
        assert row["voice_emotion_link"] == 1
        assert row["disabled_tools"] == "[]"

        # Verify ChatConfigRepository works with migrated schema
        from nous.domain.chat_config import ChatConfigRepository

        repo = ChatConfigRepository(conn)
        config = repo.get("test")
        assert config.irodori_enabled is False
        assert config.portrait_enabled is False
        assert config.voice_auto_play is False
        assert config.voice_emotion_link is True
        assert config.disabled_tools == []

        conn.close()


class TestChatConfigRepositoryResilience:
    """Resilience: corrupted/legacy data in DB should not cause crash."""

    _SCHEMA = """
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
            image_gen_comfyui_url TEXT DEFAULT '',
            image_gen_gemini_model TEXT DEFAULT 'google/gemini-2.5-flash-image',
            image_gen_replicate_model TEXT DEFAULT 'black-forest-labs/flux-schnell',
            image_gen_replicate_api_key TEXT DEFAULT '',
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
            voice_auto_play INTEGER DEFAULT 0,
            voice_emotion_link INTEGER DEFAULT 1,
            disabled_tools TEXT DEFAULT '[]'
        )
    """

    @pytest.fixture
    def db(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.row_factory = sqlite3.Row
        conn.execute(self._SCHEMA)
        conn.commit()
        yield conn
        conn.close()

    def test_corrupted_mcp_servers_json(self, db):
        """Invalid JSON in mcp_servers → fallback to []."""
        db.execute(
            "INSERT INTO chat_settings (persona, provider, mcp_servers) VALUES (?, ?, ?)",
            ("test", "anthropic", "{corrupted"),
        )
        db.commit()
        repo = ChatConfigRepository(db)
        config = repo.get("test")
        assert config.mcp_servers == []
        assert config.provider == "anthropic"  # Other fields intact

    def test_corrupted_enabled_skills_json(self, db):
        """Invalid JSON in enabled_skills → fallback to []."""
        db.execute(
            "INSERT INTO chat_settings (persona, provider, enabled_skills) VALUES (?, ?, ?)",
            ("test", "openai", "not json at all"),
        )
        db.commit()
        repo = ChatConfigRepository(db)
        config = repo.get("test")
        assert config.enabled_skills == []
        assert config.provider == "openai"

    def test_corrupted_disabled_tools_json(self, db):
        """Invalid JSON in disabled_tools → fallback to []."""
        db.execute(
            "INSERT INTO chat_settings (persona, disabled_tools) VALUES (?, ?)",
            ("test", "{{{broken"),
        )
        db.commit()
        repo = ChatConfigRepository(db)
        config = repo.get("test")
        assert config.disabled_tools == []

    def test_valid_json_wrong_type_mcp_servers(self, db):
        """Valid JSON but wrong type for mcp_servers → fallback to []."""
        db.execute(
            "INSERT INTO chat_settings (persona, provider, mcp_servers) VALUES (?, ?, ?)",
            ("test", "anthropic", '"not_a_list"'),  # valid JSON string, not list
        )
        db.commit()
        repo = ChatConfigRepository(db)
        config = repo.get("test")
        assert config.mcp_servers == []
        assert config.provider == "anthropic"

    def test_validation_error_temperature_out_of_range(self, db):
        """temperature=3.0 should be clamped to 2.0 by validator, no crash."""
        db.execute(
            "INSERT INTO chat_settings (persona, temperature) VALUES (?, ?)",
            ("test", 3.0),
        )
        db.commit()
        repo = ChatConfigRepository(db)
        config = repo.get("test")
        assert config.temperature == 2.0  # Clamped

    def test_unknown_column_in_db_not_in_model(self):
        """Extra DB columns not in ChatConfig.model_fields → silently ignored."""
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        # Use all columns from the main schema plus an extra obsolete_column
        conn.execute(
            self._SCHEMA.replace(
                "CREATE TABLE chat_settings (",
                "CREATE TABLE chat_settings (obsolete_column TEXT DEFAULT 'legacy', ",
            )
        )
        conn.execute("INSERT INTO chat_settings (persona) VALUES ('test')")
        conn.commit()
        repo = ChatConfigRepository(conn)
        config = repo.get("test")
        assert config.persona == "test"
        conn.close()

    def test_all_json_fields_corrupted(self, db):
        """All three JSON fields corrupted → all fallback to []."""
        db.execute(
            "INSERT INTO chat_settings (persona, mcp_servers, enabled_skills, disabled_tools) VALUES (?, ?, ?, ?)",
            ("test", "{bad", "[broken", "null invalid"),
        )
        db.commit()
        repo = ChatConfigRepository(db)
        config = repo.get("test")
        assert config.mcp_servers == []
        assert config.enabled_skills == []
        assert config.disabled_tools == []
