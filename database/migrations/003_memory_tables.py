import sqlite3

def up(conn: sqlite3.Connection) -> None:
    # Memories table
    conn.execute("""
        CREATE TABLE memories (
            id              TEXT PRIMARY KEY,
            type            TEXT NOT NULL,
            category        TEXT,
            tier            TEXT NOT NULL DEFAULT 'short_term',
            content         TEXT NOT NULL,
            summary         TEXT,
            source          TEXT,
            source_id       TEXT,
            
            confidence      REAL NOT NULL DEFAULT 0.5,
            importance      REAL NOT NULL DEFAULT 0.5,
            emotional_weight REAL DEFAULT 0.0,
            
            access_count    INTEGER NOT NULL DEFAULT 0,
            last_accessed_at TEXT,
            decay_rate      REAL NOT NULL DEFAULT 0.01,
            
            created_at      TEXT NOT NULL,
            updated_at      TEXT NOT NULL,
            expires_at      TEXT,
            archived_at     TEXT,
            version         INTEGER NOT NULL DEFAULT 1,
            is_protected    INTEGER NOT NULL DEFAULT 0,
            
            metadata        TEXT,
            embedding       BLOB
        )
    """)
    
    # Indices
    conn.execute("CREATE INDEX idx_mem_type ON memories(type)")
    conn.execute("CREATE INDEX idx_mem_tier ON memories(tier)")
    conn.execute("CREATE INDEX idx_mem_importance ON memories(importance DESC)")
    conn.execute("CREATE INDEX idx_mem_created ON memories(created_at DESC)")
    conn.execute("CREATE INDEX idx_mem_archived ON memories(archived_at) WHERE archived_at IS NULL")
    
    # FTS
    conn.execute("""
        CREATE VIRTUAL TABLE memories_fts USING fts5(
            content, summary, category,
            content='memories',
            content_rowid='rowid',
            tokenize='porter unicode61'
        )
    """)
    
    # FTS Triggers
    conn.execute("""
        CREATE TRIGGER mem_fts_insert AFTER INSERT ON memories BEGIN
            INSERT INTO memories_fts(rowid, content, summary, category)
            VALUES (new.rowid, new.content, new.summary, new.category);
        END;
    """)
    conn.execute("""
        CREATE TRIGGER mem_fts_delete AFTER DELETE ON memories BEGIN
            INSERT INTO memories_fts(memories_fts, rowid, content, summary, category)
            VALUES ('delete', old.rowid, old.content, old.summary, old.category);
        END;
    """)
    conn.execute("""
        CREATE TRIGGER mem_fts_update AFTER UPDATE ON memories BEGIN
            INSERT INTO memories_fts(memories_fts, rowid, content, summary, category)
            VALUES ('delete', old.rowid, old.content, old.summary, old.category);
            INSERT INTO memories_fts(rowid, content, summary, category)
            VALUES (new.rowid, new.content, new.summary, new.category);
        END;
    """)
    
    # Links
    conn.execute("""
        CREATE TABLE memory_links (
            source_id   TEXT NOT NULL,
            target_id   TEXT NOT NULL,
            link_type   TEXT NOT NULL,
            weight      REAL NOT NULL DEFAULT 1.0,
            metadata    TEXT,
            created_at  TEXT NOT NULL,
            PRIMARY KEY (source_id, target_id, link_type),
            FOREIGN KEY (source_id) REFERENCES memories(id) ON DELETE CASCADE,
            FOREIGN KEY (target_id) REFERENCES memories(id) ON DELETE CASCADE
        )
    """)
    conn.execute("CREATE INDEX idx_links_source ON memory_links(source_id)")
    
    # Versions
    conn.execute("""
        CREATE TABLE memory_versions (
            id          TEXT PRIMARY KEY,
            memory_id   TEXT NOT NULL,
            version     INTEGER NOT NULL,
            content     TEXT NOT NULL,
            confidence  REAL,
            importance  REAL,
            changed_by  TEXT,
            changed_at  TEXT NOT NULL,
            FOREIGN KEY (memory_id) REFERENCES memories(id) ON DELETE CASCADE
        )
    """)

def down(conn: sqlite3.Connection) -> None:
    conn.execute("DROP TABLE IF EXISTS memory_versions")
    conn.execute("DROP TABLE IF EXISTS memory_links")
    conn.execute("DROP TRIGGER IF EXISTS mem_fts_update")
    conn.execute("DROP TRIGGER IF EXISTS mem_fts_delete")
    conn.execute("DROP TRIGGER IF EXISTS mem_fts_insert")
    conn.execute("DROP TABLE IF EXISTS memories_fts")
    conn.execute("DROP TABLE IF EXISTS memories")
