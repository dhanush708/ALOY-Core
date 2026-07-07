import pytest
import asyncio
from database.connection import DatabaseConnectionPool
from security.audit import AuditLogger
from database.migrator import Migrator

@pytest.mark.asyncio
async def test_audit_logger(tmp_path):
    db_path = str(tmp_path / "test.db")
    pool = DatabaseConnectionPool(db_path)
    
    # Run migrations to create tables
    migrator = Migrator(pool, migrations_pkg="database.migrations")
    await migrator.migrate()
    
    logger = AuditLogger(pool)
    await logger.start()
    
    await logger.log_action(
        actor="test_user",
        action="read",
        target="file.txt",
        status="allowed",
        details={"reason": "read_allowed"}
    )
    
    # Verify in DB
    with pool.get_read_connection() as conn:
        cursor = conn.execute("SELECT * FROM audit_log WHERE actor = 'test_user'")
        row = cursor.fetchone()
        
        assert row is not None
        assert row["action"] == "read"
        assert row["target"] == "file.txt"
        assert row["status"] == "allowed"
        assert "read_allowed" in row["details"]
