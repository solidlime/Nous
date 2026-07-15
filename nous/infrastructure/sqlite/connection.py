from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from nous.infrastructure.logging.structured import get_logger

logger = get_logger(__name__)

_MEMORY_SCHEMA = """\
CREATE TABLE IF NOT EXISTS memories (
    key TEXT PRIMARY KEY,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    tags TEXT DEFAULT '[]',
    importance REAL DEFAULT 0.5,
    emotion TEXT DEFAULT 'neutral',
    emotion_intensity REAL DEFAULT 0.0,
    physical_state TEXT,
    mental_state TEXT,
    environment TEXT,
    relationship_status TEXT,
    action_tag TEXT,
    source_context TEXT,
    related_keys TEXT DEFAULT '[]',
    summary_ref TEXT,
    equipped_items TEXT,
    access_count INTEGER DEFAULT 0,
    last_accessed TEXT,
    privacy_level TEXT DEFAULT 'internal',
    body_state TEXT,
    state_snapped_at TEXT,
    lifecycle_status TEXT DEFAULT 'active',
    last_consumed_at TEXT,
    kind TEXT DEFAULT 'semantic',
    episodic_time TEXT,
    episodic_place TEXT,
    episodic_people TEXT,
    source_type TEXT DEFAULT 'user_stated',
    confidence REAL DEFAULT 1.0,
    derived_from TEXT,
    valid_from TEXT,
    valid_until TEXT
);

CREATE TABLE IF NOT EXISTS memory_strength (
    memory_key TEXT PRIMARY KEY,
    strength REAL DEFAULT 1.0,
    stability REAL DEFAULT 1.0,
    last_decay TEXT,
    recall_count INTEGER DEFAULT 0,
    last_recall TEXT,
    last_utility TEXT,
    interference_count INTEGER DEFAULT 0,
    link_count INTEGER DEFAULT 0,
    emotion_peak REAL DEFAULT 0.0,
    is_ltm INTEGER DEFAULT 0,
    valence REAL DEFAULT 0.0,
    FOREIGN KEY (memory_key) REFERENCES memories(key)
);

CREATE TABLE IF NOT EXISTS memory_blocks (
    block_name TEXT PRIMARY KEY,
    content TEXT NOT NULL,
    block_type TEXT DEFAULT 'custom',
    max_tokens INTEGER DEFAULT 500,
    priority INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    metadata TEXT DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS context_state (
    persona TEXT NOT NULL,
    key TEXT NOT NULL,
    value TEXT,
    valid_from TEXT NOT NULL,
    valid_until TEXT,
    change_source TEXT,
    author_note TEXT,
    author_note_frequency TEXT DEFAULT 'always',
    PRIMARY KEY (persona, key, valid_from)
);

CREATE TABLE IF NOT EXISTS emotion_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    emotion_type TEXT NOT NULL,
    intensity REAL DEFAULT 0.5,
    timestamp TEXT NOT NULL,
    trigger_memory_key TEXT,
    context TEXT
);

CREATE TABLE IF NOT EXISTS user_info (
    persona TEXT NOT NULL,
    key TEXT NOT NULL,
    value TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (persona, key)
);

CREATE TABLE IF NOT EXISTS persona_info (
    persona TEXT NOT NULL,
    key TEXT NOT NULL,
    value TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (persona, key)
);

CREATE TABLE IF NOT EXISTS entities (
    id TEXT PRIMARY KEY,
    entity_type TEXT NOT NULL DEFAULT 'unknown',
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    mention_count INTEGER DEFAULT 1,
    metadata TEXT DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_entities_type ON entities(entity_type);

CREATE TABLE IF NOT EXISTS entity_relations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_entity TEXT NOT NULL REFERENCES entities(id),
    target_entity TEXT NOT NULL REFERENCES entities(id),
    relation_type TEXT NOT NULL,
    memory_key TEXT,
    confidence REAL DEFAULT 1.0,
    created_at TEXT NOT NULL,
    UNIQUE(source_entity, target_entity, relation_type, memory_key)
);
CREATE INDEX IF NOT EXISTS idx_relations_source ON entity_relations(source_entity);
CREATE INDEX IF NOT EXISTS idx_relations_target ON entity_relations(target_entity);

CREATE TABLE IF NOT EXISTS memory_entities (
    memory_key TEXT NOT NULL,
    entity_id TEXT NOT NULL REFERENCES entities(id),
    role TEXT DEFAULT 'mentioned',
    PRIMARY KEY (memory_key, entity_id)
);

CREATE TABLE IF NOT EXISTS memory_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    memory_key TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    content TEXT NOT NULL,
    metadata TEXT,
    changed_by TEXT DEFAULT 'user',
    change_type TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(memory_key, version)
);
CREATE INDEX IF NOT EXISTS idx_memory_versions_key ON memory_versions(memory_key);

CREATE TABLE IF NOT EXISTS search_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    query TEXT NOT NULL,
    mode TEXT DEFAULT 'hybrid',
    result_count INTEGER DEFAULT 0,
    searched_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_search_log_time ON search_log(searched_at DESC);
CREATE INDEX IF NOT EXISTS idx_memories_updated_at ON memories(updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_memories_created_at ON memories(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_memory_strength_strength ON memory_strength(strength);
CREATE INDEX IF NOT EXISTS idx_emotion_history_persona ON emotion_history(timestamp DESC);

CREATE TABLE IF NOT EXISTS body_state_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    persona_id TEXT NOT NULL,
    fatigue REAL,
    warmth REAL,
    arousal REAL,
    heart_rate REAL,
    pain REAL,
    timestamp TEXT NOT NULL DEFAULT (datetime('now')),
    context TEXT
);
CREATE INDEX IF NOT EXISTS idx_body_state_history_persona ON body_state_history(persona_id, timestamp DESC);

CREATE TABLE IF NOT EXISTS chat_settings (
    persona     TEXT PRIMARY KEY,
    provider    TEXT DEFAULT 'anthropic',
    model       TEXT DEFAULT '',
    api_key     TEXT DEFAULT '',
    base_url    TEXT DEFAULT '',
    system_prompt TEXT DEFAULT '',
    temperature REAL DEFAULT 0.7,
    max_tokens  INTEGER DEFAULT 2048,
    max_window_turns INTEGER DEFAULT 3,
    max_tool_calls INTEGER DEFAULT 5,
    updated_at  TEXT,
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
    dynamic_tool_selection INTEGER DEFAULT 1,
    irodori_enabled INTEGER DEFAULT 0,
    portrait_enabled INTEGER DEFAULT 0,
    voice_auto_play INTEGER DEFAULT 0,
    voice_emotion_link INTEGER DEFAULT 1,
    voice_model TEXT DEFAULT '',
    image_gen_gemini_model TEXT DEFAULT 'google/gemini-2.5-flash-image',
    image_gen_replicate_model TEXT DEFAULT 'black-forest-labs/flux-schnell',
    image_gen_replicate_api_key TEXT DEFAULT '',
    disabled_tools TEXT DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS session_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    persona TEXT NOT NULL,
    event_type TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    summary TEXT NOT NULL,
    detail TEXT,
    metadata_json TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_session_events_session ON session_events(session_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_session_events_persona ON session_events(persona, timestamp);
CREATE INDEX IF NOT EXISTS idx_session_events_type ON session_events(event_type, timestamp);

CREATE TABLE IF NOT EXISTS memory_links (
    source_key TEXT NOT NULL,
    target_key TEXT NOT NULL,
    weight REAL NOT NULL DEFAULT 0.5,
    link_type TEXT NOT NULL DEFAULT 'semantic',
    co_activation_count INTEGER DEFAULT 0,
    last_activated TEXT,
    PRIMARY KEY (source_key, target_key, link_type)
);
CREATE INDEX IF NOT EXISTS idx_links_source ON memory_links(source_key);
CREATE INDEX IF NOT EXISTS idx_links_target ON memory_links(target_key);
"""

_INVENTORY_SCHEMA = """\
CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    category TEXT,
    description TEXT,
    visual_desc TEXT,
    quantity INTEGER DEFAULT 1,
    tags TEXT DEFAULT '[]',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS equipment_slots (
    slot TEXT PRIMARY KEY,
    item_name TEXT,
    equipped_at TEXT
);

CREATE TABLE IF NOT EXISTS equipment_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action TEXT NOT NULL,
    slot TEXT,
    item_name TEXT,
    timestamp TEXT NOT NULL,
    details TEXT
);
"""


_CHAT_SESSIONS_SCHEMA = """\
CREATE TABLE IF NOT EXISTS chat_sessions (
    persona     TEXT NOT NULL,
    session_id  TEXT NOT NULL,
    messages    TEXT NOT NULL DEFAULT '[]',
    timestamps  TEXT NOT NULL DEFAULT '[]',
    updated_at  TEXT NOT NULL,
    PRIMARY KEY (persona, session_id)
);
"""

_SKILLS_SCHEMA = """\
CREATE TABLE IF NOT EXISTS skills (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT UNIQUE NOT NULL,
    description   TEXT DEFAULT '',
    content       TEXT NOT NULL DEFAULT '',
    license       TEXT,
    compatibility TEXT,
    metadata      TEXT,
    created_at    TEXT,
    updated_at    TEXT
);
"""

_global_skills_conn: sqlite3.Connection | None = None


def get_global_skills_db(data_dir: str) -> sqlite3.Connection:
    """Return the singleton global skills.sqlite connection."""
    global _global_skills_conn
    if _global_skills_conn is None:
        db_path = Path(data_dir) / "skills" / "skills.sqlite"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(db_path), check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.row_factory = sqlite3.Row
        conn.executescript(_SKILLS_SCHEMA)
        conn.commit()
        _global_skills_conn = conn
        logger.info("Global skills DB opened: %s", db_path)
    return _global_skills_conn


class SQLiteConnection:
    """SQLite connection manager with WAL mode and per-persona DB isolation."""

    def __init__(self, data_dir: str, persona: str) -> None:
        self.data_dir = data_dir
        self.persona = persona
        self._lock = threading.Lock()
        self._connections: dict[str, sqlite3.Connection] = {}

    def get_memory_db(self) -> sqlite3.Connection:
        """Get connection to memory.sqlite for this persona."""
        return self._get_or_create(f"{self.persona}/memory.sqlite")

    def get_inventory_db(self) -> sqlite3.Connection:
        """Get connection to inventory.sqlite for this persona."""
        return self._get_or_create(f"{self.persona}/inventory.sqlite")

    def _get_or_create(self, relative_path: str) -> sqlite3.Connection:
        with self._lock:
            if relative_path not in self._connections:
                db_path = Path(self.data_dir) / relative_path
                db_path.parent.mkdir(parents=True, exist_ok=True)
                conn = sqlite3.connect(str(db_path), check_same_thread=False)
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA foreign_keys=ON")
                conn.row_factory = sqlite3.Row
                self._connections[relative_path] = conn
                logger.info("SQLite connection opened: %s", db_path)
            return self._connections[relative_path]

    def initialize_schema(self) -> None:
        """Create all tables if they don't exist."""
        memory_conn = self.get_memory_db()
        memory_conn.executescript(_MEMORY_SCHEMA + _CHAT_SESSIONS_SCHEMA)
        memory_conn.commit()
        logger.info("Memory schema initialized for persona '%s'", self.persona)

        # Migration: add last_consumed_at if missing (existing DBs)
        try:
            memory_conn.execute("ALTER TABLE memories ADD COLUMN last_consumed_at TEXT")
            memory_conn.commit()
            logger.info("Added last_consumed_at column to memories (migration)")
        except sqlite3.OperationalError:
            pass  # column already exists

        # Migration: add irodori_enabled if missing (existing DBs)
        try:
            memory_conn.execute("ALTER TABLE chat_settings ADD COLUMN irodori_enabled INTEGER DEFAULT 0")
            memory_conn.commit()
            logger.info("Added irodori_enabled column to chat_settings (migration)")
        except sqlite3.OperationalError:
            pass  # column already exists

        # Migration: add portrait_enabled if missing (existing DBs)
        try:
            memory_conn.execute("ALTER TABLE chat_settings ADD COLUMN portrait_enabled INTEGER DEFAULT 0")
            memory_conn.commit()
            logger.info("Added portrait_enabled column to chat_settings (migration)")
        except sqlite3.OperationalError:
            pass  # column already exists

        # Migration: add voice_auto_play, voice_emotion_link, voice_model if missing (existing DBs, TE04)
        for col, default in [("voice_auto_play", 0), ("voice_emotion_link", 1)]:
            try:
                memory_conn.execute(f"ALTER TABLE chat_settings ADD COLUMN {col} INTEGER DEFAULT {default}")
                memory_conn.commit()
                logger.info("Added %s column to chat_settings (migration)", col)
            except sqlite3.OperationalError:
                pass  # column already exists
        try:
            memory_conn.execute("ALTER TABLE chat_settings ADD COLUMN voice_model TEXT DEFAULT ''")
            memory_conn.commit()
            logger.info("Added voice_model column to chat_settings (migration)")
        except sqlite3.OperationalError:
            pass  # column already exists

        # Migration: add image_gen_comfyui_url if missing (existing DBs)
        try:
            memory_conn.execute("ALTER TABLE chat_settings ADD COLUMN image_gen_comfyui_url TEXT DEFAULT ''")
            memory_conn.commit()
            logger.info("Added image_gen_comfyui_url column to chat_settings (migration)")
        except sqlite3.OperationalError:
            pass  # column already exists

        # Migration: add image_gen_gemini_model, replicate fields if missing
        for col, col_type, default in [
            ("image_gen_gemini_model", "TEXT", "'google/gemini-2.5-flash-image'"),
            ("image_gen_replicate_model", "TEXT", "'black-forest-labs/flux-schnell'"),
            ("image_gen_replicate_api_key", "TEXT", "''"),
        ]:
            try:
                memory_conn.execute(f"ALTER TABLE chat_settings ADD COLUMN {col} {col_type} DEFAULT {default}")
                memory_conn.commit()
                logger.info("Added %s column to chat_settings (migration)", col)
            except sqlite3.OperationalError:
                pass  # column already exists

        # Migration: add remaining chat_settings columns if missing (existing DBs)
        _chat_settings_migrations = [
            ("enable_memory_tools", "INTEGER", 1),
            ("debug_mode", "INTEGER", 0),
            ("dynamic_temperature", "INTEGER", 1),
            ("emotion_temperature_scale", "REAL", 0.2),
            ("top_p", "REAL", "NULL"),
            ("context_use_llm_summary", "INTEGER", 1),
            ("episode_consolidation_enabled", "INTEGER", 1),
            ("episode_search_enabled", "INTEGER", 1),
            ("dynamic_tool_selection", "INTEGER", 1),
            ("retrieval_rrf_k", "REAL", 5.0),
            ("disabled_tools", "TEXT", "'[]'"),
        ]
        for col, col_type, default in _chat_settings_migrations:
            try:
                memory_conn.execute(f"ALTER TABLE chat_settings ADD COLUMN {col} {col_type} DEFAULT {default}")
                memory_conn.commit()
                logger.info("Added %s column to chat_settings (migration)", col)
            except sqlite3.OperationalError:
                pass  # column already exists

        # One-shot migration: context_state -> memories (temporary)
        try:
            from nous.infrastructure.sqlite.migration_one_shot import (  # noqa: PLC0415
                migrate_context_state_to_memories,
            )

            migrated = migrate_context_state_to_memories(memory_conn, self.persona)
            if migrated:
                memory_conn.commit()
                logger.info("One-shot migration: %d state records -> memories", migrated)
        except Exception:
            pass

        # Initialize FTS5 full-text search index
        self._init_fts_schema(memory_conn)

        inventory_conn = self.get_inventory_db()
        inventory_conn.executescript(_INVENTORY_SCHEMA)
        inventory_conn.commit()
        logger.info("Inventory schema initialized for persona '%s'", self.persona)

    def _init_fts_schema(self, conn: sqlite3.Connection) -> None:
        """Create FTS5 virtual table and sync triggers for full-text search.

        Uses a standalone FTS5 table (not external-content) with its own copy of
        ``content`` and a ``memories_key`` column for JOINs. Triggers use standard
        SQL ``DELETE FROM`` (the FTS5-specific ``'delete'`` command is not available
        in bundled libsqlite3 3.46).
        """
        conn.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
                content,
                memories_key UNINDEXED,
                tokenize='unicode61'
            )
            """
        )
        conn.execute(
            """
            CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
                INSERT INTO memories_fts(rowid, content, memories_key)
                VALUES (new.rowid, new.content, new.key);
            END
            """
        )
        conn.execute(
            """
            CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
                DELETE FROM memories_fts WHERE rowid = old.rowid;
            END
            """
        )
        conn.execute(
            """
            CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN
                DELETE FROM memories_fts WHERE rowid = old.rowid;
                INSERT INTO memories_fts(rowid, content, memories_key)
                VALUES (new.rowid, new.content, new.key);
            END
            """
        )
        # Backfill FTS5 index if empty (migration from non-FTS5 DB)
        count = conn.execute("SELECT COUNT(*) as cnt FROM memories_fts").fetchone()["cnt"]
        if count == 0:
            existing = conn.execute("SELECT COUNT(*) as cnt FROM memories").fetchone()["cnt"]
            if existing > 0:
                conn.execute(
                    "INSERT INTO memories_fts(rowid, content, memories_key) SELECT rowid, content, key FROM memories"
                )
                logger.info("FTS5 index backfilled: %d documents", existing)
        conn.commit()
        logger.info("FTS5 schema initialized for persona '%s'", self.persona)

    def close(self) -> None:
        """Close all managed connections."""
        with self._lock:
            for path, conn in self._connections.items():
                try:
                    conn.close()
                    logger.info("SQLite connection closed: %s", path)
                except Exception as e:
                    logger.warning("Error closing SQLite connection %s: %s", path, e)
            self._connections.clear()
