import sqlite3

def up(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE reasoning_logs (
            id              TEXT PRIMARY KEY,
            query           TEXT NOT NULL,
            strategy        TEXT NOT NULL,
            depth           TEXT NOT NULL,
            steps           TEXT NOT NULL,          -- JSON array of steps
            final_output    TEXT NOT NULL,
            confidence      REAL,
            use_count       INTEGER DEFAULT 0,
            created_at      TEXT NOT NULL,
            expires_at      TEXT NOT NULL           -- TTL timestamp
        )
    """)
    conn.execute("CREATE INDEX idx_reasoning_logs_query ON reasoning_logs(query)")
    conn.execute("CREATE INDEX idx_reasoning_logs_expires ON reasoning_logs(expires_at)")

def down(conn: sqlite3.Connection) -> None:
    conn.execute("DROP INDEX IF EXISTS idx_reasoning_logs_expires")
    conn.execute("DROP INDEX IF EXISTS idx_reasoning_logs_query")
    conn.execute("DROP TABLE IF EXISTS reasoning_logs")
