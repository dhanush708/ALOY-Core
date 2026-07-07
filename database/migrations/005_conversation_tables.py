import sqlite3

def up(conn: sqlite3.Connection) -> None:
    # Conversations table
    conn.execute("""
        CREATE TABLE conversations (
            id                  TEXT PRIMARY KEY,
            title               TEXT,
            turn_count          INTEGER NOT NULL DEFAULT 0,
            current_intent      TEXT,
            emotional_tone      TEXT NOT NULL DEFAULT 'neutral',
            topic_stack         TEXT,  -- JSON list
            active_memories     TEXT,  -- JSON list
            user_mood_estimate  TEXT,
            last_model_used     TEXT,
            context_token_count INTEGER NOT NULL DEFAULT 0,
            started_at          TEXT NOT NULL,
            last_activity       TEXT NOT NULL
        )
    """)
    
    # Conversation Messages (History)
    conn.execute("""
        CREATE TABLE conversation_messages (
            id              TEXT PRIMARY KEY,
            conversation_id TEXT NOT NULL,
            role            TEXT NOT NULL, -- 'user', 'assistant', 'system', 'tool'
            content         TEXT NOT NULL,
            name            TEXT,          -- for tool calls
            token_count     INTEGER,
            metadata        TEXT,          -- JSON dict for extra context
            created_at      TEXT NOT NULL,
            FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
        )
    """)
    conn.execute("CREATE INDEX idx_conv_msg_conv_id ON conversation_messages(conversation_id, created_at)")
    
def down(conn: sqlite3.Connection) -> None:
    conn.execute("DROP TABLE IF EXISTS conversation_messages")
    conn.execute("DROP TABLE IF EXISTS conversations")
