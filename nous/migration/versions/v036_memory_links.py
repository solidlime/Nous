"""v036: Create memory_links table for Hebbian associative network (Collins & Loftus 1975)."""


def upgrade(db) -> None:
    db.execute("""
        CREATE TABLE IF NOT EXISTS memory_links (
            source_key TEXT NOT NULL,
            target_key TEXT NOT NULL,
            weight REAL NOT NULL DEFAULT 0.5,
            link_type TEXT NOT NULL DEFAULT 'semantic',
            co_activation_count INTEGER DEFAULT 0,
            last_activated TEXT,
            PRIMARY KEY (source_key, target_key, link_type)
        )
    """)
    db.execute("CREATE INDEX IF NOT EXISTS idx_links_source ON memory_links(source_key)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_links_target ON memory_links(target_key)")
    db.commit()
