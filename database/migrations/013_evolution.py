import sqlite3


def up(conn: sqlite3.Connection) -> None:
    # Evolution Proposals
    conn.execute("""
        CREATE TABLE IF NOT EXISTS evolution_proposals (
            id                   TEXT PRIMARY KEY,
            problem              TEXT NOT NULL,
            evidence             TEXT NOT NULL,
            possible_solutions   TEXT NOT NULL,  -- JSON list
            recommended_solution TEXT NOT NULL,
            affected_files       TEXT NOT NULL,  -- JSON list
            benefits             TEXT NOT NULL,
            risks                TEXT NOT NULL,
            implementation_plan  TEXT NOT NULL,  -- Markdown plan
            status               TEXT NOT NULL DEFAULT 'pending', -- pending, approved, rejected, applied
            created_at           TEXT NOT NULL,
            metadata             TEXT            -- JSON dict
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_evolution_proposals_status ON evolution_proposals(status)")


def down(conn: sqlite3.Connection) -> None:
    conn.execute("DROP INDEX IF EXISTS idx_evolution_proposals_status")
    conn.execute("DROP TABLE IF EXISTS evolution_proposals")
