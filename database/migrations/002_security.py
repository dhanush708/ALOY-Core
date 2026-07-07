import sqlite3

def up(conn: sqlite3.Connection) -> None:
    # Security Policies table
    conn.execute("""
        CREATE TABLE security_policies (
            id          TEXT PRIMARY KEY,
            name        TEXT NOT NULL UNIQUE,
            rules       TEXT NOT NULL,
            is_active   INTEGER NOT NULL DEFAULT 1,
            created_at  TEXT NOT NULL,
            updated_at  TEXT NOT NULL
        )
    """)
    
    # Audit Log table
    conn.execute("""
        CREATE TABLE audit_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            actor       TEXT NOT NULL,
            action      TEXT NOT NULL,
            target      TEXT NOT NULL,
            status      TEXT NOT NULL,
            timestamp   TEXT NOT NULL,
            details     TEXT
        )
    """)
    conn.execute("CREATE INDEX idx_audit_actor_time ON audit_log(actor, timestamp DESC)")
    
    # Session Approvals table
    conn.execute("""
        CREATE TABLE session_approvals (
            session_id      TEXT NOT NULL,
            action_pattern  TEXT NOT NULL,
            approved_at     TEXT NOT NULL,
            expires_at      TEXT NOT NULL,
            PRIMARY KEY (session_id, action_pattern)
        )
    """)

def down(conn: sqlite3.Connection) -> None:
    conn.execute("DROP TABLE IF EXISTS session_approvals")
    conn.execute("DROP TABLE IF EXISTS audit_log")
    conn.execute("DROP TABLE IF EXISTS security_policies")
