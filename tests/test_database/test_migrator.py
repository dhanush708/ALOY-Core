import pytest
import os
import sqlite3
from database.connection import DatabaseConnectionPool
from database.migrator import Migrator

@pytest.mark.asyncio
async def test_migrator_up_down(tmp_path):
    db_path = str(tmp_path / "test.db")
    pool = DatabaseConnectionPool(db_path)
    
    migrator = Migrator(pool, migrations_pkg="database.migrations")
    
    # Initially no tables except _migrations
    with pool.get_read_connection() as conn:
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row["name"] for row in cursor.fetchall()]
        assert "telemetry" not in tables
        
    # Migrate up
    applied = await migrator.migrate()
    assert len(applied) > 0
    
    # Check tables exist
    with pool.get_read_connection() as conn:
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row["name"] for row in cursor.fetchall()]
        assert "telemetry" in tables
        assert "prompts" in tables
        
    # Migrate down
    rolled_back = await migrator.rollback(count=len(applied))
    assert len(rolled_back) > 0
    
    # Check tables are gone
    with pool.get_read_connection() as conn:
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row["name"] for row in cursor.fetchall()]
        assert "telemetry" not in tables
        assert "prompts" not in tables
