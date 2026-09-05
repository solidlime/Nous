"""Tests for ChatConfig model and the legacy SQLite→config.json migration path."""

from __future__ import annotations

import json
import sqlite3

from nous.domain.chat_config import ChatConfig, ChatConfigFileRepository


class TestSqliteMigration:
    """Verify ALTER TABLE ADD COLUMN for existing databases + the one-shot
    memory.sqlite → config.json upgrade path (ChatConfigFileRepository)."""

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
                max_tokens INTEGER DEFAULT 8192,
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
                display_history_turns INTEGER DEFAULT 10,
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
                image_gen_provider TEXT DEFAULT 'comfyui',
                image_gen_comfyui_url TEXT DEFAULT '',
                image_gen_comfyui_checkpoint TEXT DEFAULT 'noobaiXLNAIXL_epsilonPred11Version.safetensors',
                image_gen_comfyui_loras TEXT DEFAULT '',
                image_gen_comfyui_width INTEGER DEFAULT 1024,
                image_gen_comfyui_height INTEGER DEFAULT 1024,
                image_gen_comfyui_steps INTEGER DEFAULT 28,
                image_gen_comfyui_cfg REAL DEFAULT 5.5,
                image_gen_comfyui_sampler TEXT DEFAULT 'euler_ancestral',
                image_gen_comfyui_scheduler TEXT DEFAULT 'normal',
                image_gen_comfyui_seed INTEGER DEFAULT 0,
                image_gen_comfyui_denoise REAL DEFAULT 0.7,
                image_gen_self_portrait_prompt TEXT DEFAULT '',
                image_gen_max_width INTEGER DEFAULT 1200,
                image_gen_max_height INTEGER DEFAULT 1200,
                image_gen_comfyui_speed_lora_path TEXT DEFAULT '',
                image_gen_comfyui_speed_lora_weight REAL DEFAULT 1.0,
                image_gen_comfyui_speed_lora_method TEXT DEFAULT 'lcm',
                enable_memory_tools INTEGER DEFAULT 1,
                debug_mode INTEGER DEFAULT 0,
                dynamic_temperature INTEGER DEFAULT 1,
                emotion_temperature_scale REAL DEFAULT 0.2,
                top_p REAL,
                context_use_llm_summary INTEGER DEFAULT 1,
                episode_search_enabled INTEGER DEFAULT 1,
                dynamic_tool_selection INTEGER DEFAULT 1
            )
        """
        conn.execute(pre_phase1_schema)
        conn.commit()

        # Simulate the migration: ALTER TABLE ADD COLUMN for each new field
        for col_sql in [
            "voice_auto_play INTEGER DEFAULT 0",
            "voice_emotion_link INTEGER DEFAULT 1",
            "voice_model TEXT DEFAULT ''",
            "voice_url TEXT DEFAULT ''",
            "voice_volume REAL DEFAULT 1.0",
            "irodori_num_steps INTEGER DEFAULT 30",
            "irodori_cfg_scale_text REAL DEFAULT 3.2",
            "irodori_cfg_scale_speaker REAL DEFAULT 5.0",
            "irodori_cfg_scale_caption REAL DEFAULT 4.2",
            "irodori_chunk_min_chars INTEGER DEFAULT 85",
            "irodori_seed INTEGER",
            "image_gen_comfyui_checkpoint TEXT DEFAULT 'noobaiXLNAIXL_epsilonPred11Version.safetensors'",
            "image_gen_comfyui_loras TEXT DEFAULT ''",
            "image_gen_comfyui_width INTEGER DEFAULT 1024",
            "image_gen_comfyui_height INTEGER DEFAULT 1024",
            "image_gen_comfyui_steps INTEGER DEFAULT 28",
            "image_gen_comfyui_cfg REAL DEFAULT 5.5",
            "image_gen_comfyui_sampler TEXT DEFAULT 'euler_ancestral'",
            "image_gen_comfyui_scheduler TEXT DEFAULT 'normal'",
            "image_gen_comfyui_seed INTEGER DEFAULT 0",
            "image_gen_comfyui_denoise REAL DEFAULT 0.7",
            "image_gen_max_width INTEGER DEFAULT 1200",
            "image_gen_max_height INTEGER DEFAULT 1200",
            "image_gen_comfyui_speed_lora_path TEXT DEFAULT ''",
            "image_gen_comfyui_speed_lora_weight REAL DEFAULT 1.0",
            "image_gen_comfyui_speed_lora_method TEXT DEFAULT 'lcm'",
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
        assert "voice_auto_play" in columns
        assert "voice_emotion_link" in columns
        assert "disabled_tools" in columns

        # Verify defaults work
        conn.execute("INSERT INTO chat_settings (persona) VALUES ('test')")
        conn.commit()
        row = conn.execute("SELECT * FROM chat_settings WHERE persona = 'test'").fetchone()
        assert row["voice_auto_play"] == 0
        assert row["voice_emotion_link"] == 1
        assert row["disabled_tools"] == "[]"

        conn.close()

    def test_migrate_from_sqlite_to_config_json(self, tmp_path):
        """Legacy memory.sqlite chat_settings → config.json one-shot upgrade."""
        data_root = tmp_path / "data"
        persona_dir = data_root / "persona" / "legacy"
        persona_dir.mkdir(parents=True)

        # Build a legacy memory.sqlite with a chat_settings row (raw SQL —
        # the SQLite repo class no longer exists)
        conn = sqlite3.connect(persona_dir / "memory.sqlite")
        conn.row_factory = sqlite3.Row
        conn.execute(
            """
            CREATE TABLE chat_settings (
                persona TEXT PRIMARY KEY,
                provider TEXT DEFAULT 'anthropic',
                model TEXT DEFAULT '',
                api_key TEXT DEFAULT '',
                temperature REAL DEFAULT 0.7,
                max_tokens INTEGER DEFAULT 8192,
                max_tool_calls INTEGER DEFAULT 5,
                updated_at TEXT,
                mcp_servers TEXT DEFAULT '[]',
                enabled_skills TEXT DEFAULT '[]',
                disabled_tools TEXT DEFAULT '[]',
                voice_auto_play INTEGER DEFAULT 0,
                top_p REAL
            )
            """
        )
        conn.execute(
            "INSERT INTO chat_settings (persona, provider, model, temperature, voice_auto_play) "
            "VALUES ('legacy', 'openrouter', 'openai/gpt-4o', 0.5, 1)"
        )
        conn.commit()
        conn.close()

        repo = ChatConfigFileRepository(str(data_root))
        config = repo.get("legacy")

        # Migrated values from the legacy SQLite row
        assert config.provider == "openrouter"
        assert config.model == "openai/gpt-4o"
        assert config.temperature == 0.5
        assert config.voice_auto_play is True  # INTEGER 1 → bool
        # config.json now exists with the migrated content
        assert (persona_dir / "config.json").exists()
        saved = ChatConfig(**json.loads((persona_dir / "config.json").read_text(encoding="utf-8")))
        assert saved.provider == "openrouter"

    def test_migrate_missing_sqlite_returns_defaults(self, tmp_path):
        """No memory.sqlite → defaults, no crash."""
        data_root = tmp_path / "data"
        (data_root / "persona" / "fresh").mkdir(parents=True)
        repo = ChatConfigFileRepository(str(data_root))
        config = repo.get("fresh")
        assert config.persona == "fresh"
        assert config.provider == "anthropic"
