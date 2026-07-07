import sqlite3

def up(conn: sqlite3.Connection) -> None:
    # Prompt metrics table
    conn.execute("""
        CREATE TABLE prompt_metrics (
            prompt_name    TEXT NOT NULL,
            prompt_version TEXT NOT NULL,
            metric_name    TEXT NOT NULL,
            metric_value   REAL NOT NULL,
            sample_count   INTEGER NOT NULL DEFAULT 1,
            measured_at    TEXT NOT NULL,
            PRIMARY KEY (prompt_name, prompt_version, metric_name),
            FOREIGN KEY (prompt_name, prompt_version) REFERENCES prompts(name, version) ON DELETE CASCADE
        )
    """)

def down(conn: sqlite3.Connection) -> None:
    conn.execute("DROP TABLE IF EXISTS prompt_metrics")
