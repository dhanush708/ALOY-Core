import sqlite3


def up(conn: sqlite3.Connection) -> None:
    # ------------------------------------------------------------------
    # Memory Tags  (many-to-many: memory ↔ tag string)
    # ------------------------------------------------------------------
    conn.execute("""
        CREATE TABLE IF NOT EXISTS memory_tags (
            memory_id  TEXT NOT NULL,
            tag        TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (memory_id, tag),
            FOREIGN KEY (memory_id) REFERENCES memories(id) ON DELETE CASCADE
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_mem_tags_tag ON memory_tags(tag)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_mem_tags_mid ON memory_tags(memory_id)")

    # ------------------------------------------------------------------
    # Memory Collections  (workspace / user / project / global scope)
    # ------------------------------------------------------------------
    conn.execute("""
        CREATE TABLE IF NOT EXISTS memory_collections (
            id          TEXT PRIMARY KEY,
            name        TEXT NOT NULL,
            scope       TEXT NOT NULL DEFAULT 'global',
            scope_id    TEXT,
            description TEXT,
            metadata    TEXT,
            created_at  TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_col_scope ON memory_collections(scope, scope_id)
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS memory_collection_members (
            collection_id TEXT NOT NULL,
            memory_id     TEXT NOT NULL,
            added_at      TEXT NOT NULL,
            PRIMARY KEY (collection_id, memory_id),
            FOREIGN KEY (collection_id) REFERENCES memory_collections(id) ON DELETE CASCADE,
            FOREIGN KEY (memory_id)     REFERENCES memories(id)           ON DELETE CASCADE
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_col_members_mid
        ON memory_collection_members(memory_id)
    """)

    # ------------------------------------------------------------------
    # Consolidation Audit Log
    # ------------------------------------------------------------------
    conn.execute("""
        CREATE TABLE IF NOT EXISTS mem_consolidation_log (
            id             TEXT PRIMARY KEY,
            run_at         TEXT NOT NULL,
            promoted       INTEGER NOT NULL DEFAULT 0,
            compressed     INTEGER NOT NULL DEFAULT 0,
            merged         INTEGER NOT NULL DEFAULT 0,
            archived       INTEGER NOT NULL DEFAULT 0,
            clusters_found INTEGER NOT NULL DEFAULT 0,
            duration_ms    INTEGER NOT NULL DEFAULT 0
        )
    """)


def down(conn: sqlite3.Connection) -> None:
    conn.execute("DROP TABLE IF EXISTS mem_consolidation_log")
    conn.execute("DROP TABLE IF EXISTS memory_collection_members")
    conn.execute("DROP TABLE IF EXISTS memory_collections")
    conn.execute("DROP INDEX IF EXISTS idx_mem_tags_mid")
    conn.execute("DROP INDEX IF EXISTS idx_mem_tags_tag")
    conn.execute("DROP TABLE IF EXISTS memory_tags")
