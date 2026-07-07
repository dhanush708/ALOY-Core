import sqlite3


def up(conn: sqlite3.Connection) -> None:
    # Agent sessions
    conn.execute("""
        CREATE TABLE IF NOT EXISTS agent_sessions (
            id          TEXT PRIMARY KEY,
            project_id  TEXT NOT NULL,
            goal        TEXT NOT NULL,
            status      TEXT NOT NULL DEFAULT 'planning',
            created_at  TEXT NOT NULL,
            updated_at  TEXT NOT NULL,
            metadata    TEXT,
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_agent_sessions_proj ON agent_sessions(project_id)")

    # Agent plans
    conn.execute("""
        CREATE TABLE IF NOT EXISTS agent_plans (
            id                 TEXT PRIMARY KEY,
            session_id         TEXT NOT NULL UNIQUE,
            steps              TEXT NOT NULL,
            current_step_index INTEGER NOT NULL DEFAULT 0,
            created_at         TEXT NOT NULL,
            FOREIGN KEY (session_id) REFERENCES agent_sessions(id) ON DELETE CASCADE
        )
    """)

    # Agent tasks
    conn.execute("""
        CREATE TABLE IF NOT EXISTS agent_tasks (
            id             TEXT PRIMARY KEY,
            session_id     TEXT NOT NULL,
            parent_task_id TEXT,
            assigned_agent TEXT NOT NULL,
            title          TEXT NOT NULL,
            description    TEXT NOT NULL,
            priority       INTEGER NOT NULL DEFAULT 5,
            status         TEXT NOT NULL DEFAULT 'pending',
            retry_count    INTEGER NOT NULL DEFAULT 0,
            max_retries    INTEGER NOT NULL DEFAULT 3,
            depends_on     TEXT DEFAULT '[]',
            result         TEXT,
            error          TEXT,
            created_at     TEXT NOT NULL,
            updated_at     TEXT NOT NULL,
            metadata       TEXT,
            FOREIGN KEY (session_id)     REFERENCES agent_sessions(id) ON DELETE CASCADE,
            FOREIGN KEY (parent_task_id) REFERENCES agent_tasks(id)    ON DELETE SET NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_agent_tasks_session ON agent_tasks(session_id, status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_agent_tasks_priority ON agent_tasks(priority, created_at)")

    # Agent checkpoints
    conn.execute("""
        CREATE TABLE IF NOT EXISTS agent_checkpoints (
            id            TEXT PRIMARY KEY,
            session_id    TEXT NOT NULL,
            step_index    INTEGER NOT NULL,
            snapshot_path TEXT NOT NULL,
            state_data    TEXT NOT NULL,
            created_at    TEXT NOT NULL,
            FOREIGN KEY (session_id) REFERENCES agent_sessions(id) ON DELETE CASCADE
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_agent_checkpoints_session ON agent_checkpoints(session_id, step_index)")

    # Workspace locks
    conn.execute("""
        CREATE TABLE IF NOT EXISTS workspace_locks (
            workspace_path TEXT PRIMARY KEY,
            session_id     TEXT NOT NULL,
            acquired_at    TEXT NOT NULL,
            expires_at     TEXT NOT NULL
        )
    """)


def down(conn: sqlite3.Connection) -> None:
    conn.execute("DROP TABLE IF EXISTS workspace_locks")
    conn.execute("DROP INDEX IF EXISTS idx_agent_checkpoints_session")
    conn.execute("DROP TABLE IF EXISTS agent_checkpoints")
    conn.execute("DROP INDEX IF EXISTS idx_agent_tasks_priority")
    conn.execute("DROP INDEX IF EXISTS idx_agent_tasks_session")
    conn.execute("DROP TABLE IF EXISTS agent_tasks")
    conn.execute("DROP TABLE IF EXISTS agent_plans")
    conn.execute("DROP INDEX IF EXISTS idx_agent_sessions_proj")
    conn.execute("DROP TABLE IF EXISTS agent_sessions")
