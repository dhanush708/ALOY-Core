import sqlite3

def up(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE user_feedback (
            id              TEXT PRIMARY KEY,
            conversation_id TEXT NOT NULL,
            message_id      TEXT NOT NULL,
            feedback_type   TEXT NOT NULL,       -- 'thumbs_up', 'thumbs_down', 'correction'
            feedback_text   TEXT,
            created_at      TEXT NOT NULL,
            processed       INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
        )
    """)
    conn.execute("CREATE INDEX idx_user_feedback_unprocessed ON user_feedback(processed) WHERE processed = 0")

def down(conn: sqlite3.Connection) -> None:
    conn.execute("DROP INDEX IF EXISTS idx_user_feedback_unprocessed")
    conn.execute("DROP TABLE IF EXISTS user_feedback")
