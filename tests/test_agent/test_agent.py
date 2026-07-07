import os
import json
import asyncio
import tempfile
from pathlib import Path
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock

from database.connection import DatabaseConnectionPool
from database.migrator import Migrator
from project.manager import ProjectManager
from kernel.event_bus import EventBus
from kernel.types import Event
from tools.system import ToolSystem
from tools.registry import ToolRegistry
from security.sandbox import Sandbox

from agent.types import TaskStep, ExecutionContext, TaskStatus, AgentSessionState, TaskResult
from agent.context import ExecutionContextBuilder
from agent.registry import AgentRegistry
from agent.task_queue import AgentTaskQueue
from agent.lock import WorkspaceLockManager
from agent.snapshot import WorkspaceSnapshotManager
from agent.triggers import AgentTriggerClassifier
from agent.metrics import RuntimeMetricsCollector
from agent.journal import ExecutionJournalWriter
from agent.agents.manager import ManagerAgent
from agent.agents.planner import PlannerAgent
from agent.agents.coder import CodingAgent
from agent.agents.tester import TestingAgent
from agent.agents.reviewer import ReviewAgent


@pytest_asyncio.fixture
async def db_pool(tmp_path):
    """Initializes in-memory database and runs all migrations."""
    db_file = str(Path(tmp_path).resolve() / "test_agents.db")
    pool = DatabaseConnectionPool(db_file)
    await pool.start()
    
    migrator = Migrator(pool, migrations_pkg="database.migrations")
    await migrator.migrate()
    
    yield pool
    await pool.stop()


@pytest_asyncio.fixture
async def event_bus():
    bus = EventBus()
    await bus.start()
    yield bus
    await bus.stop()


@pytest_asyncio.fixture
async def project_manager(db_pool):
    return ProjectManager(db_pool)


@pytest.fixture
def workspace_dir(tmp_path):
    ws = Path(tmp_path).resolve() / "workspace"
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "src").mkdir(parents=True, exist_ok=True)
    with open(ws / "src" / "main.py", "w", encoding="utf-8") as f:
        f.write("print('hello')\n")
    return ws


# 1. Test Trigger Classifier
@pytest.mark.asyncio
async def test_trigger_classifier():
    classifier = AgentTriggerClassifier()
    assert await classifier.classify("implement a quicksort function in python") == "coding"
    assert await classifier.classify("search the web for Apple stock") == "knowledge"
    assert await classifier.classify("hello") == "conversation"


# 2. Test ExecutionContext serialization
def test_execution_context_serialization(workspace_dir):
    ctx = ExecutionContextBuilder.build(
        session_id="session-123",
        project_id="project-456",
        goal="Build feature A",
        workspace_path=str(workspace_dir),
        manifest={"project": {"name": "test-project"}},
    )

    serialized = ExecutionContextBuilder.serialize(ctx)
    assert serialized["session_id"] == "session-123"
    assert serialized["workspace_path"] == str(workspace_dir).replace("\\", "/")

    deserialized = ExecutionContextBuilder.deserialize(serialized)
    assert deserialized.session_id == "session-123"
    assert deserialized.workspace_path == str(workspace_dir).replace("\\", "/")
    assert deserialized.goal == "Build feature A"


# 3. Test WorkspaceLockManager
@pytest.mark.asyncio
async def test_workspace_lock_manager(db_pool, event_bus, workspace_dir):
    ws_path = str(workspace_dir)
    lock_mgr = WorkspaceLockManager(db_pool, event_bus)

    # First lock acquisition should succeed
    assert await lock_mgr.acquire(ws_path, "session-1") is True
    assert await lock_mgr.is_locked(ws_path) is True

    # Concurrent acquisition by another session should fail
    assert await lock_mgr.acquire(ws_path, "session-2") is False

    # Refreshing lock by same session should succeed
    assert await lock_mgr.acquire(ws_path, "session-1") is True

    # Releasing lock
    await lock_mgr.release(ws_path, "session-1")
    assert await lock_mgr.is_locked(ws_path) is False


# 4. Test WorkspaceSnapshotManager
@pytest.mark.asyncio
async def test_workspace_snapshot_manager(workspace_dir):
    snapshot_mgr = WorkspaceSnapshotManager()
    ws_path = str(workspace_dir)

    # Modify a file before snapshot
    main_file = workspace_dir / "src" / "main.py"
    with open(main_file, "w", encoding="utf-8") as f:
        f.write("first version\n")

    # Take snapshot
    ref = await snapshot_mgr.create_snapshot(ws_path, "session-1")
    assert ref.startswith("zip:") or ref.startswith("git:")

    # Modify the file again
    with open(main_file, "w", encoding="utf-8") as f:
        f.write("second version\n")

    # Restore snapshot
    await snapshot_mgr.restore_snapshot(ws_path, ref)

    # Verify content restored
    with open(main_file, "r", encoding="utf-8") as f:
        content = f.read()
    assert content == "first version\n"

    # Cleanup snapshot
    await snapshot_mgr.delete_snapshot(ws_path, ref)


# 5. Test AgentTaskQueue dependency resolution
@pytest.mark.asyncio
async def test_agent_task_queue(db_pool):
    queue = AgentTaskQueue(db_pool)
    session_id = "session-1"

    # We need a session row in agent_sessions to fetch next task
    now = "2026-06-23T12:00:00"
    with db_pool.get_write_connection() as conn:
        conn.execute(
            "INSERT INTO projects (id, name, root_path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            ("project-1", "Test Project", "dummy_path", now, now)
        )
        conn.execute(
            "INSERT INTO agent_sessions (id, project_id, goal, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (session_id, "project-1", "Build it", "executing", now, now)
        )

    # Create task 1 (no dependencies)
    t1 = await queue.create_task(session_id, "coder", "Task 1", "desc")
    # Create task 2 (depends on task 1)
    t2 = await queue.create_task(session_id, "tester", "Task 2", "desc", depends_on=[t1.id])

    # Next task should be Task 1
    next_task = await queue.get_next_task(session_id)
    assert next_task is not None
    assert next_task.id == t1.id

    # Mark Task 1 done
    await queue.mark_done(t1.id, "success")

    # Next task should now be Task 2 (dependency satisfied)
    next_task = await queue.get_next_task(session_id)
    assert next_task is not None
    assert next_task.id == t2.id


# 6. Test Planner Agent
@pytest.mark.asyncio
async def test_planner_agent(workspace_dir):
    agent = PlannerAgent()
    task = TaskStep("t1", "s1", "planner", "Plan", "Decompose")
    context = ExecutionContextBuilder.build("s1", "p1", "Add login page", str(workspace_dir), {})

    model_router = AsyncMock()
    model_router.generate = AsyncMock(return_value=json.dumps([
        {"id": "a1", "assigned_agent": "architect", "title": "Scan code", "description": "Scan", "depends_on": []},
        {"id": "c1", "assigned_agent": "coder", "title": "Add form", "description": "Add", "depends_on": ["a1"]}
    ]))

    result = await agent.execute(task, context, AsyncMock(), model_router)
    assert result.success is True
    plan = json.loads(result.result)
    assert len(plan) == 2
    assert plan[0]["assigned_agent"] == "architect"


# 7. Test Coder Agent
@pytest.mark.asyncio
async def test_coder_agent(workspace_dir):
    agent = CodingAgent()
    task = TaskStep("t1", "s1", "coder", "Code", "Write login logic", metadata={"file_path": "src/login.py"})
    context = ExecutionContextBuilder.build("s1", "p1", "Goal", str(workspace_dir), {})

    model_router = AsyncMock()
    model_router.generate = AsyncMock(return_value="def login(): pass")

    tool_system = AsyncMock()
    tool_system.execute = AsyncMock(return_value="Wrote characters successfully")

    result = await agent.execute(task, context, tool_system, model_router)
    assert result.success is True
    tool_system.execute.assert_called_once()
    args, kwargs = tool_system.execute.call_args
    assert args[0] == "file_editor"
    assert args[1]["action"] == "write"
    assert "src/login.py" in args[1]["path"]


# 8. Test ManagerAgent run loop
@pytest.mark.asyncio
async def test_manager_agent_run_loop(db_pool, event_bus, workspace_dir):
    ws_path = str(workspace_dir)
    session_id = "session-test-loop"
    project_id = "project-1"

    # Register project in project table first
    now = "2026-06-23T12:00:00"
    with db_pool.get_write_connection() as conn:
        conn.execute(
            """
            INSERT INTO projects (id, name, root_path, created_at, updated_at) 
            VALUES (?, ?, ?, ?, ?)
            """,
            (project_id, "Test Project", ws_path, now, now)
        )
        conn.execute(
            """
            INSERT INTO agent_sessions (id, project_id, goal, status, created_at, updated_at) 
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (session_id, project_id, "Test Goal", "planning", now, now)
        )

    task_queue = AgentTaskQueue(db_pool)
    registry = AgentRegistry()
    lock_mgr = WorkspaceLockManager(db_pool, event_bus)
    snapshot_mgr = WorkspaceSnapshotManager()
    metrics_collector = RuntimeMetricsCollector()

    # Mock tools and router
    model_router = AsyncMock()
    # Planner response
    model_router.generate = AsyncMock(return_value=json.dumps([
        {"id": "arch_1", "assigned_agent": "architect", "title": "Scan", "description": "Scan details", "depends_on": []}
    ]))

    tool_system = AsyncMock()
    tool_system.execute = AsyncMock(return_value="Success")

    # Specialized agents registered
    planner = PlannerAgent()
    architect = MagicMock()
    architect.name = "architect"
    architect.execute = AsyncMock(return_value=TaskResult(success=True, result="Arch details"))

    # We also mock reviewer, documenter, learner completion steps
    documenter = MagicMock()
    documenter.name = "documenter"
    documenter.execute = AsyncMock(return_value=TaskResult(success=True))
    learner = MagicMock()
    learner.name = "learner"
    learner.execute = AsyncMock(return_value=TaskResult(success=True))

    registry.register("planner", planner)
    registry.register("architect", architect)
    registry.register("documenter", documenter)
    registry.register("learner", learner)

    manager = ManagerAgent(
        db_pool=db_pool,
        task_queue=task_queue,
        registry=registry,
        lock_manager=lock_mgr,
        snapshot_manager=snapshot_mgr,
        event_bus=event_bus,
    )
    registry.register("manager", manager)

    # Initialize ExecutionContext
    context = ExecutionContextBuilder.build(
        session_id=session_id,
        project_id=project_id,
        goal="Test Goal",
        workspace_path=ws_path,
        manifest={},
    )

    # Run Manager loop
    await manager.run(session_id, context, tool_system, model_router)

    # Verify session completed successfully in DB
    with db_pool.get_read_connection() as conn:
        row = conn.execute("SELECT status FROM agent_sessions WHERE id = ?", (session_id,)).fetchone()
    assert row[0] == AgentSessionState.COMPLETED.value
