import sqlite3

def up(conn: sqlite3.Connection) -> None:
    # Prompts table
    conn.execute("""
        CREATE TABLE prompts (
            name        TEXT NOT NULL,
            version     TEXT NOT NULL,
            template    TEXT NOT NULL,
            variables   TEXT,
            model_hint  TEXT,
            is_active   INTEGER NOT NULL DEFAULT 1,
            created_at  TEXT NOT NULL,
            metadata    TEXT,
            PRIMARY KEY (name, version)
        )
    """)
    conn.execute("CREATE INDEX idx_prompts_active ON prompts(name, is_active) WHERE is_active = 1")
    
    # Telemetry tables
    conn.execute("""
        CREATE TABLE telemetry (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            metric      TEXT NOT NULL,
            value       REAL NOT NULL,
            tags        TEXT,
            timestamp   TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX idx_telemetry_metric_time ON telemetry(metric, timestamp DESC)")
    
    conn.execute("""
        CREATE TABLE telemetry_aggregates (
            metric       TEXT NOT NULL,
            period       TEXT NOT NULL,
            period_start TEXT NOT NULL,
            avg_value    REAL,
            min_value    REAL,
            max_value    REAL,
            count        INTEGER,
            PRIMARY KEY (metric, period, period_start)
        )
    """)

def down(conn: sqlite3.Connection) -> None:
    conn.execute("DROP TABLE IF EXISTS telemetry_aggregates")
    conn.execute("DROP TABLE IF EXISTS telemetry")
    conn.execute("DROP TABLE IF EXISTS prompts")
