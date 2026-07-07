import os
import shutil
import zipfile
import sqlite3
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from database.connection import DatabaseConnectionPool
from database.migrator import Migrator
from memory.decay import DecayEngine
from memory.manager import MemoryManager
from agent.snapshot import WorkspaceSnapshotManager
from security.rollback import AdvancedRollbackEngine
from database.backup import DatabaseBackupManager
from fastapi.testclient import TestClient
from api.server import app

@pytest.fixture
def temp_db(tmp_path):
    db_file = tmp_path / "test_security.db"
    pool = DatabaseConnectionPool(str(db_file))
    # Run migrations
    import asyncio
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(pool.start())
    migrator = Migrator(pool, migrations_pkg="database.migrations")
    loop.run_until_complete(migrator.migrate())
    yield pool, db_file
    loop.run_until_complete(pool.stop())
    loop.close()

# 1. Test GFS Backup Manager and rotation
def test_backup_manager_rotation(tmp_path):
    db_file = tmp_path / "live.db"
    # Create simple sqlite db
    conn = sqlite3.connect(db_file)
    conn.execute("CREATE TABLE t (id INT)")
    conn.commit()
    conn.close()

    backup_dir = tmp_path / "backups"
    manager = DatabaseBackupManager(str(db_file), str(backup_dir))

    # Assert directories created
    assert manager.daily_dir.exists()
    assert manager.weekly_dir.exists()
    assert manager.monthly_dir.exists()

    # Pre-populate bucket with old backups to test rotation limit
    for i in range(10):
        daily_old = manager.daily_dir / f"backup_daily_2026-06-{i:02d}.db"
        daily_old.write_text("dummy")

    # Run backup
    manager.create_backup()

    # Verify daily has rotated and kept exactly 7
    daily_files = list(manager.daily_dir.glob("backup_daily_*.db"))
    assert len(daily_files) == 7

    # Verify weekly and monthly created
    assert len(list(manager.weekly_dir.glob("backup_weekly_*.db"))) == 1
    assert len(list(manager.monthly_dir.glob("backup_monthly_*.db"))) == 1

# 2. Test Advanced Rollback Engine (Zip-based rollback)
@pytest.mark.asyncio
async def test_surgical_rollback_zip(tmp_path, temp_db):
    db_pool, db_file = temp_db
    workspace = tmp_path / "ws"
    workspace.mkdir()
    
    # Pre-create snapshots folder to prevent FileNotFoundError
    (tmp_path / "snaps").mkdir(parents=True, exist_ok=True)
    
    # 1. Create file and take snapshot
    file_to_change = workspace / "src" / "app.py"
    file_to_change.parent.mkdir(parents=True, exist_ok=True)
    file_to_change.write_text("initial content")

    snapshot_mgr = WorkspaceSnapshotManager(snapshots_dir=tmp_path / "snaps")
    snapshot_ref = await snapshot_mgr.create_snapshot(str(workspace), "session-123")

    # 2. Modify file and add new file
    file_to_change.write_text("modified content")
    new_file = workspace / "src" / "new.py"
    new_file.write_text("new content")

    # Record checkpoint in DB
    with db_pool.get_write_connection() as conn:
        # Register project
        conn.execute("INSERT INTO projects (id, name, root_path, created_at, updated_at) VALUES ('p1', 'proj', ?, '2026-06-23', '2026-06-23')", (str(workspace),))
        # Register session
        conn.execute("INSERT INTO agent_sessions (id, project_id, goal, status, created_at, updated_at) VALUES ('session-123', 'p1', 'goal', 'executing', '2026-06-23', '2026-06-23')")
        # Register checkpoint with non-null state_data
        conn.execute(
            "INSERT INTO agent_checkpoints (id, session_id, step_index, snapshot_path, state_data, created_at) VALUES ('chk-1', 'session-123', 1, ?, '{}', '2026-06-23')",
            (snapshot_ref,)
        )

    # 3. Surgical Revert modified file
    engine = AdvancedRollbackEngine(db_pool, snapshot_mgr)
    success = await engine.revert_single_file("session-123", "chk-1", str(file_to_change))
    assert success
    assert file_to_change.read_text() == "initial content"

    # 4. Surgical Revert new file (revert should delete it)
    assert new_file.exists()
    success = await engine.revert_single_file("session-123", "chk-1", str(new_file))
    assert success
    assert not new_file.exists()

# 3. Test Memory Protection Decay Gating
@pytest.mark.asyncio
async def test_memory_protection_decay(temp_db):
    db_pool, _ = temp_db
    
    # Insert two memories, one protected and one unprotected
    mgr = MemoryManager(db_pool)
    await mgr.start()

    m_protected = await mgr.store("episodic", "Critical core architecture rule", importance=1.0, is_protected=1)
    m_unprotected = await mgr.store("episodic", "Temporary meeting note", importance=0.8, is_protected=0)

    # Re-fetch check protection status
    ref_p = await mgr.get(m_protected.id)
    ref_u = await mgr.get(m_unprotected.id)
    assert ref_p.is_protected == 1
    assert ref_u.is_protected == 0

    # Set access time and creation time to long ago to force decay/archival
    # Set both to ensure the parser always gets a past date
    with db_pool.get_write_connection() as conn:
        conn.execute("""
            UPDATE memories 
            SET decay_rate = 1.0, 
                created_at = '2026-01-01T12:00:00+00:00',
                last_accessed_at = '2026-01-01T12:00:00+00:00'
        """)

    # Run decay
    decayed, archived = await mgr.decay_engine.process_decay()
    
    # Unprotected should decay/archive, protected must bypass
    assert archived >= 1
    
    # Assert protected remains active
    active_p = await mgr.get(m_protected.id)
    assert active_p is not None
    assert active_p.archived_at is None

    # Assert unprotected is archived
    active_u = await mgr.get(m_unprotected.id)
    assert active_u.archived_at is not None

    # Check delete API refuses deletion of protected memory unless forced
    deleted = await mgr.delete(m_protected.id, force=False)
    assert not deleted
    
    deleted_forced = await mgr.delete(m_protected.id, force=True)
    assert deleted_forced

# 4. Test Security API Endpoints
def test_security_api_endpoints():
    mock_backup = MagicMock()
    mock_backup.create_backup.return_value = "/path/to/backup.db"
    mock_backup.list_backups.return_value = [{"name": "b1", "path": "/path/b1", "bucket": "daily", "created_at": "2026-06-23", "size_bytes": 100}]
    mock_backup.restore_backup.return_value = None

    mock_rollback = MagicMock()
    mock_rollback.revert_single_file = AsyncMock(return_value=True)

    mock_memory = MagicMock()
    mock_memory.protect_memory = AsyncMock(return_value=True)

    app.state.backup_manager = mock_backup
    app.state.rollback_engine = mock_rollback
    app.state.memory_manager = mock_memory

    client = TestClient(app)

    # POST /api/security/backup
    response = client.post("/api/security/backup")
    assert response.status_code == 200
    assert response.json()["backup_path"] == "/path/to/backup.db"

    # GET /api/security/backups
    response = client.get("/api/security/backups")
    assert response.status_code == 200
    assert response.json()[0]["name"] == "b1"

    # POST /api/security/backup/restore
    response = client.post("/api/security/backup/restore", json={"backup_path": "/path/b1"})
    assert response.status_code == 200
    mock_backup.restore_backup.assert_called_with("/path/b1")

    # POST /api/security/memory/protect
    response = client.post("/api/security/memory/protect", json={"memory_id": "m1", "is_protected": True})
    assert response.status_code == 200
    mock_memory.protect_memory.assert_called_with("m1", True)

    # POST /api/security/rollback/file
    response = client.post("/api/security/rollback/file", json={
        "session_id": "s1",
        "checkpoint_id": "c1",
        "file_path": "src/main.py"
    })
    assert response.status_code == 200
    mock_rollback.revert_single_file.assert_called_with("s1", "c1", "src/main.py")
