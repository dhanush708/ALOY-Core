import sqlite3


def up(conn: sqlite3.Connection) -> None:
    # Projects table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS projects (
            id            TEXT PRIMARY KEY,
            name          TEXT NOT NULL,
            root_path     TEXT NOT NULL UNIQUE,
            manifest_path TEXT,
            created_at    TEXT NOT NULL,
            updated_at    TEXT NOT NULL,
            metadata      TEXT
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_projects_root ON projects(root_path)")

    # Project sessions table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS project_sessions (
            id         TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            started_at TEXT NOT NULL,
            ended_at   TEXT,
            summary    TEXT,
            metadata   TEXT,
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_project_sessions_proj ON project_sessions(project_id)")

    # Project files table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS project_files (
            id              TEXT PRIMARY KEY,
            project_id      TEXT NOT NULL,
            file_path       TEXT NOT NULL,
            file_type       TEXT,
            last_indexed_at TEXT NOT NULL,
            metadata        TEXT,
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
            UNIQUE (project_id, file_path)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_project_files_proj ON project_files(project_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_project_files_path ON project_files(file_path)")


def down(conn: sqlite3.Connection) -> None:
    conn.execute("DROP INDEX IF EXISTS idx_project_files_path")
    conn.execute("DROP INDEX IF EXISTS idx_project_files_proj")
    conn.execute("DROP TABLE IF EXISTS project_files")
    conn.execute("DROP INDEX IF EXISTS idx_project_sessions_proj")
    conn.execute("DROP TABLE IF EXISTS project_sessions")
    conn.execute("DROP INDEX IF EXISTS idx_projects_root")
    conn.execute("DROP TABLE IF EXISTS projects")
