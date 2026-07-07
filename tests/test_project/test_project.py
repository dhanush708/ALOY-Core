import pytest
import pytest_asyncio
import tempfile
import os
import shutil
from pathlib import Path
from datetime import datetime, timezone

from database.connection import DatabaseConnectionPool
from database.migrator import Migrator
from project.manifest import ManifestLoader
from project.tree import DirectoryTreeBuilder
from project.discovery import ProjectDiscovery
from project.session import ProjectSession
from project.manager import ProjectManager


@pytest.fixture
def temp_workspace():
    """Sets up a temporary folder to serve as project/workspace root."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir).resolve()
        
        # Create some files and folders
        os.makedirs(tmp_path / "src")
        os.makedirs(tmp_path / "tests")
        os.makedirs(tmp_path / "node_modules")
        
        with open(tmp_path / "main.py", "w") as f:
            f.write("print('hello')")
            
        with open(tmp_path / "src" / "utils.py", "w") as f:
            f.write("def helper(): pass")
            
        with open(tmp_path / "tests" / "test_main.py", "w") as f:
            f.write("def test_func(): pass")
            
        with open(tmp_path / "app.log", "w") as f:
            f.write("some logs")
            
        with open(tmp_path / "node_modules" / "index.js", "w") as f:
            f.write("module.exports = {}")
            
        yield tmp_path


@pytest_asyncio.fixture
async def project_manager(tmp_path):
    """Initializes in-memory test database and returns ProjectManager."""
    db_path = str(Path(tmp_path).resolve() / "test_projects.db")
    pool = DatabaseConnectionPool(db_path)
    
    # Run migrations
    migrator = Migrator(pool, migrations_pkg="database.migrations")
    await migrator.migrate()
    
    manager = ProjectManager(pool)
    yield manager
    
    await pool.stop()


def test_manifest_loader(temp_workspace):
    # Load defaults
    data = ManifestLoader.load(temp_workspace)
    assert data["project"]["name"] == temp_workspace.name
    assert ".git" in data["project"]["exclude_patterns"]
    
    # Init manifest
    manifest_path = ManifestLoader.init_manifest(temp_workspace, "TestProj", "Test Desc")
    assert manifest_path.exists()
    assert manifest_path.name == "manifest.yaml"
    
    # Load initialized manifest
    data2 = ManifestLoader.load(temp_workspace)
    assert data2["project"]["name"] == "TestProj"
    assert data2["project"]["description"] == "Test Desc"
    
    # Save manifest updates
    data2["project"]["version"] = "2.1.0"
    data2["project"]["exclude_patterns"].append("custom_pattern")
    ManifestLoader.save(temp_workspace, data2)
    
    data3 = ManifestLoader.load(temp_workspace)
    assert data3["project"]["version"] == "2.1.0"
    assert "custom_pattern" in data3["project"]["exclude_patterns"]


def test_directory_tree_builder(temp_workspace):
    exclude_patterns = [".aloy", "node_modules", "*.log"]
    
    # 1. Nested Dictionary Tree representation
    tree = DirectoryTreeBuilder.build(temp_workspace, exclude_patterns)
    assert tree["name"] == temp_workspace.name
    assert tree["type"] == "directory"
    
    # Find main.py
    children_names = [c["name"] for c in tree["children"]]
    assert "main.py" in children_names
    assert "src" in children_names
    assert "tests" in children_names
    assert "app.log" not in children_names
    assert "node_modules" not in children_names
    
    # 2. Flat List builder
    flat_paths = DirectoryTreeBuilder.build_flat(temp_workspace, exclude_patterns)
    rel_paths = [p.relative_to(temp_workspace).as_posix() for p in flat_paths]
    assert "main.py" in rel_paths
    assert "src/utils.py" in rel_paths
    assert "tests/test_main.py" in rel_paths
    assert "app.log" not in rel_paths
    assert "node_modules/index.js" not in rel_paths
    
    # 3. String Tree Builder representation
    tree_str = DirectoryTreeBuilder.to_string(tree)
    assert temp_workspace.name in tree_str
    assert "main.py" in tree_str
    assert "utils.py" in tree_str


def test_project_discovery(temp_workspace):
    # Start clean
    assert ProjectDiscovery.is_project_root(temp_workspace) is False
    
    # Add a marker
    with open(temp_workspace / "pyproject.toml", "w") as f:
        f.write("[tool.poetry]")
        
    assert ProjectDiscovery.is_project_root(temp_workspace) is True
    
    # Find root from a subfolder
    subfolder = temp_workspace / "src"
    root = ProjectDiscovery.find_project_root(subfolder)
    assert root == temp_workspace
    
    # Scan child dirs for project roots
    parent_dir = temp_workspace.parent
    projects = ProjectDiscovery.scan_for_projects(parent_dir)
    assert temp_workspace in projects


@pytest.mark.asyncio
async def test_project_manager_crud(project_manager, temp_workspace):
    # Register project
    proj = project_manager.create_project(
        name="Test Project",
        root_path=temp_workspace,
        description="My test description",
        metadata={"custom_val": 42}
    )
    
    assert proj["id"] is not None
    assert proj["name"] == "Test Project"
    assert proj["root_path"] == temp_workspace.resolve().as_posix()
    assert proj["metadata"]["custom_val"] == 42
    
    # Get project
    p = project_manager.get_project(proj["id"])
    assert p is not None
    assert p["name"] == "Test Project"
    
    # Get project by root path
    p2 = project_manager.get_project_by_root(temp_workspace)
    assert p2 is not None
    assert p2["id"] == proj["id"]
    
    # List projects
    plist = project_manager.list_projects()
    assert len(plist) == 1
    assert plist[0]["id"] == proj["id"]
    
    # Delete project
    deleted = project_manager.delete_project(proj["id"])
    assert deleted is True
    assert project_manager.get_project(proj["id"]) is None


@pytest.mark.asyncio
async def test_project_sessions(project_manager, temp_workspace):
    proj = project_manager.create_project("SessionProj", temp_workspace)
    proj_id = proj["id"]
    
    # Start session
    session = project_manager.start_session(proj_id, {"env": "test"})
    assert session.id is not None
    assert session.project_id == proj_id
    assert session.metadata["env"] == "test"
    assert session.ended_at is None
    
    # Get active session
    active = project_manager.get_active_session(proj_id)
    assert active is not None
    assert active.id == session.id
    
    # Log some session changes
    session.log_change("src/utils.py", "modify")
    session.log_command("pytest tests/", 0)
    
    # End session
    ended = project_manager.end_session(
        session,
        summary="Finished testing project module",
        metadata={"success": True}
    )
    
    assert ended is not None
    assert ended.id == session.id
    assert ended.ended_at is not None
    assert ended.summary == "Finished testing project module"
    assert ended.metadata["success"] is True
    assert len(ended.metadata["changes"]) == 1
    assert len(ended.metadata["commands"]) == 1
    
    # Verify active session is now None
    assert project_manager.get_active_session(proj_id) is None
    
    # List sessions
    slist = project_manager.list_sessions(proj_id)
    assert len(slist) == 1
    assert slist[0].id == session.id


@pytest.mark.asyncio
async def test_project_indexing(project_manager, temp_workspace):
    proj = project_manager.create_project("IndexedProj", temp_workspace)
    proj_id = proj["id"]
    
    # Index files
    stats = project_manager.index_project_files(proj_id)
    # Excludes default folder exclusions (like node_modules, temp_workspace/.aloy)
    # Expected disk files: main.py, src/utils.py, tests/test_main.py, app.log (no logger filter since we did not update manifest exclude patterns)
    assert stats["added"] > 0
    assert stats["removed"] == 0
    assert stats["updated"] == 0
    
    # Verify files stored in DB
    with project_manager.db_pool.get_read_connection() as conn:
        rows = conn.execute("SELECT file_path, file_type FROM project_files WHERE project_id = ?", (proj_id,)).fetchall()
        files = {r["file_path"]: r["file_type"] for r in rows}
        
    assert "main.py" in files
    assert files["main.py"] == "py"
    assert "src/utils.py" in files
    
    # Add a file, re-scan
    with open(temp_workspace / "new_file.txt", "w") as f:
        f.write("new content")
        
    stats2 = project_manager.index_project_files(proj_id)
    assert stats2["added"] == 1
    assert stats2["removed"] == 0
    assert stats2["updated"] == 0
    
    # Update a file, re-scan
    # Wait, we need to modify mtime/size
    full_path = temp_workspace / "main.py"
    with open(full_path, "w") as f:
        f.write("print('hello modified!!!!!!')")
    
    # Force modify mtime to future
    os.utime(full_path, (datetime.now().timestamp() + 100, datetime.now().timestamp() + 100))
    
    stats3 = project_manager.index_project_files(proj_id)
    assert stats3["updated"] == 1
    
    # Delete a file, re-scan
    os.remove(temp_workspace / "new_file.txt")
    stats4 = project_manager.index_project_files(proj_id)
    assert stats4["removed"] == 1
    assert stats4["added"] == 0
    
    # Cascade delete verification
    project_manager.delete_project(proj_id)
    
    with project_manager.db_pool.get_read_connection() as conn:
        c_files = conn.execute("SELECT COUNT(*) as cnt FROM project_files WHERE project_id = ?", (proj_id,)).fetchone()["cnt"]
        c_sessions = conn.execute("SELECT COUNT(*) as cnt FROM project_sessions WHERE project_id = ?", (proj_id,)).fetchone()["cnt"]
        
    assert c_files == 0
    assert c_sessions == 0
