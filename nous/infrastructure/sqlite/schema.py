"""DDL schema definitions for SQLite databases.

All CREATE TABLE / INDEX / FTS5 statements are centralised here so that
:py:mod:`~nous.infrastructure.sqlite.connection` can focus on connection
management only.
"""

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
    context TEXT,
    persona TEXT NOT NULL DEFAULT ''
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
CREATE INDEX IF NOT EXISTS idx_emotion_history_persona ON emotion_history(persona);
CREATE INDEX IF NOT EXISTS idx_emotion_history_timestamp ON emotion_history(timestamp DESC);

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
