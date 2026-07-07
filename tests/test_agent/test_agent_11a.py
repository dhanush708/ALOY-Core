import os
import json
import asyncio
from pathlib import Path
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock

from database.connection import DatabaseConnectionPool
from database.migrator import Migrator
from project.manager import ProjectManager
from kernel.event_bus import EventBus
from kernel.types import Event
from agent.types import TaskStep, ExecutionContext, TaskStatus, AgentSessionState, TaskResult
from agent.context import ExecutionContextBuilder
from agent.registry import AgentRegistry
from agent.task_queue import AgentTaskQueue
from agent.lock import WorkspaceLockManager
from agent.snapshot import WorkspaceSnapshotManager
from agent.metrics import RuntimeMetricsCollector
from agent.journal import ExecutionJournalWriter
from agent.agents.manager import ManagerAgent
from agent.agents.planner import PlannerAgent
from agent.agents.coder import CodingAgent
from agent.agents.debugger import DebugAgent

from agent.fsm import AgentSessionFSM, InvalidStateTransitionError
from agent.ast_inspector import ASTInspector
from agent.checkpoint_resume import CheckpointResumeManager


@pytest_asyncio.fixture
async def db_pool(tmp_path):
    """Initializes in-memory database and runs all migrations."""
    db_file = str(Path(tmp_path).resolve() / "test_agents_11a.db")
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


@pytest.fixture
def workspace_dir(tmp_path):
    ws = Path(tmp_path).resolve() / "workspace"
    ws.mkdir(parents=True, exist_ok=True)
    return ws


# 1. Test AgentSessionFSM
@pytest.mark.asyncio
async def test_agent_session_fsm(db_pool):
    session_id = "session-fsm-1"
    now = "2026-06-23T12:00:00"
    with db_pool.get_write_connection() as conn:
        conn.execute(
            "INSERT INTO projects (id, name, root_path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            ("proj-1", "Test Project", "dummy_path", now, now)
        )
        conn.execute(
            "INSERT INTO agent_sessions (id, project_id, goal, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (session_id, "proj-1", "Build X", "planning", now, now)
        )

    fsm = AgentSessionFSM(db_pool)
    assert await fsm.get_state(session_id) == AgentSessionState.PLANNING

    # Valid transition: PLANNING -> EXECUTING
    await fsm.transition_to(session_id, AgentSessionState.EXECUTING)
    assert await fsm.get_state(session_id) == AgentSessionState.EXECUTING

    # Invalid transition: EXECUTING -> COMPLETED (must go through REVIEWING)
    with pytest.raises(InvalidStateTransitionError):
        await fsm.transition_to(session_id, AgentSessionState.COMPLETED)

    # Valid transitions: EXECUTING -> REVIEWING -> COMPLETED
    await fsm.transition_to(session_id, AgentSessionState.REVIEWING)
    await fsm.transition_to(session_id, AgentSessionState.COMPLETED)
    assert await fsm.get_state(session_id) == AgentSessionState.COMPLETED


# 2. Test ASTInspector
def test_ast_inspector():
    code = """
import os
from math import pi as PI

class Calculator:
    \"\"\"Docstring for class Calculator.\"\"\"
    def add(self, a, b):
        \"\"\"Adds two numbers.\"\"\"
        return a + b

def global_func():
    pass
"""
    result = ASTInspector.inspect_code(code)
    assert result["syntax_valid"] is True
    assert result["error"] is None

    # Verify imports
    assert len(result["imports"]) == 2
    assert result["imports"][0]["module"] == "os"
    assert result["imports"][1]["module"] == "math.pi"
    assert result["imports"][1]["name"] == "PI"

    # Verify classes
    assert len(result["classes"]) == 1
    assert result["classes"][0]["name"] == "Calculator"
    assert "Calculator" in result["classes"][0]["docstring"]

    # Verify functions (methods are functions in AST walk)
    assert len(result["functions"]) == 2
    func_names = [f["name"] for f in result["functions"]]
    assert "add" in func_names
    assert "global_func" in func_names
    
    # Verify syntax error handling
    invalid_code = "class Calculator:"
    err_res = ASTInspector.inspect_code(invalid_code)
    assert err_res["syntax_valid"] is False
    assert "SyntaxError" in err_res["error"]


# 3. Test CheckpointResumeManager
@pytest.mark.asyncio
async def test_checkpoint_resume_manager(db_pool, workspace_dir):
    session_id = "session-resume-1"
    now = "2026-06-23T12:00:00"
    
    # Setup session and plans in DB
    with db_pool.get_write_connection() as conn:
        conn.execute(
            "INSERT INTO projects (id, name, root_path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            ("proj-1", "Proj", str(workspace_dir), now, now)
        )
        conn.execute(
            "INSERT INTO agent_sessions (id, project_id, goal, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (session_id, "proj-1", "Goal", "failed", now, now)
        )
        conn.execute(
            "INSERT INTO agent_plans (id, session_id, steps, current_step_index, created_at) VALUES (?, ?, ?, ?, ?)",
            ("plan-1", session_id, "[]", 2, now)
        )

    # Setup tasks
    task_queue = AgentTaskQueue(db_pool)
    t1 = await task_queue.create_task(session_id, "coder", "Task 1", "desc")
    t2 = await task_queue.create_task(session_id, "tester", "Task 2", "desc")
    
    # Mark t1 done, t2 running
    await task_queue.mark_done(t1.id, "result")
    await task_queue.mark_running(t2.id)
    with db_pool.get_write_connection() as conn:
        conn.execute("UPDATE agent_tasks SET status = 'failed', error = 'crash' WHERE id = ?", (t2.id,))

    # Create dummy snapshot
    snapshot_mgr = WorkspaceSnapshotManager()
    main_file = workspace_dir / "main.py"
    with open(main_file, "w", encoding="utf-8") as f:
        f.write("v1\n")
    snapshot_ref = await snapshot_mgr.create_snapshot(str(workspace_dir), session_id)
    
    # Save checkpoint in DB
    checkpoint_id = "chk-1"
    with db_pool.get_write_connection() as conn:
        conn.execute(
            "INSERT INTO agent_checkpoints (id, session_id, step_index, snapshot_path, state_data, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (checkpoint_id, session_id, 1, snapshot_ref, "{}", now)
        )

    # Modify workspace files to simulate further progress / corruption
    with open(main_file, "w", encoding="utf-8") as f:
        f.write("v2\n")

    # Run resume from checkpoint
    resume_mgr = CheckpointResumeManager(db_pool, task_queue, snapshot_mgr)
    await resume_mgr.resume_from_checkpoint(session_id, checkpoint_id, str(workspace_dir))

    # Verify workspace restored to v1
    with open(main_file, "r", encoding="utf-8") as f:
        content = f.read()
    assert content == "v1\n"

    # Verify session is back to EXECUTING status and plan index back to 1
    with db_pool.get_read_connection() as conn:
        session_row = conn.execute("SELECT status FROM agent_sessions WHERE id = ?", (session_id,)).fetchone()
        plan_row = conn.execute("SELECT current_step_index FROM agent_plans WHERE session_id = ?", (session_id,)).fetchone()
        t2_row = conn.execute("SELECT status, error FROM agent_tasks WHERE id = ?", (t2.id,)).fetchone()

    assert session_row[0] == AgentSessionState.EXECUTING.value
    assert plan_row[0] == 1
    
    # Verify t2 (failed task) is back to pending and error cleared
    assert t2_row[0] == "pending"
    assert t2_row[1] is None

    # Cleanup snapshot
    await snapshot_mgr.delete_snapshot(str(workspace_dir), snapshot_ref)


# 4. Test Coder Agent Surgical Diff Editing
@pytest.mark.asyncio
async def test_coder_agent_surgical_diff(workspace_dir):
    agent = CodingAgent()
    task = TaskStep("t1", "s1", "coder", "Code", "Modify function", metadata={"file_path": "main.py"})
    context = ExecutionContextBuilder.build("s1", "p1", "Goal", str(workspace_dir), {})

    model_router = AsyncMock()
    # Return SEARCH/REPLACE blocks
    model_router.generate = AsyncMock(return_value="<<<<<<< SEARCH\nv1\n=======\nv_new\n>>>>>>> REPLACE")

    # Setup the file first
    with open(workspace_dir / "main.py", "w", encoding="utf-8") as f:
        f.write("v1\n")

    tool_system = AsyncMock()
    tool_system.execute = AsyncMock(return_value="Applied diff successfully")

    result = await agent.execute(task, context, tool_system, model_router)
    assert result.success is True
    tool_system.execute.assert_called_once()
    args, kwargs = tool_system.execute.call_args
    assert args[0] == "diff_engine"
    assert args[1]["path"].endswith("main.py")
    assert "<<<<<<< SEARCH" in args[1]["patch"]


# 5. Test Mistake Avoidance Memory query
@pytest.mark.asyncio
async def test_mistake_avoidance_memory(workspace_dir):
    # Mock MemoryManager
    memory_manager = AsyncMock()
    mock_memory = MagicMock()
    mock_memory.content = "Avoid using deprecated module"
    mock_scored = MagicMock()
    mock_scored.memory = mock_memory
    memory_manager.retrieve_with_profile = AsyncMock(return_value=[mock_scored])

    agent = CodingAgent(memory_manager=memory_manager)
    task = TaskStep("t1", "s1", "coder", "Code", "Fix bug X", metadata={"file_path": "main.py"})
    context = ExecutionContextBuilder.build("s1", "p1", "Goal", str(workspace_dir), {})

    model_router = AsyncMock()
    model_router.generate = AsyncMock(return_value="fixed code")

    tool_system = AsyncMock()
    tool_system.execute = AsyncMock(return_value="Success")

    result = await agent.execute(task, context, tool_system, model_router)
    assert result.success is True

    # Verify memory_manager was queried
    memory_manager.retrieve_with_profile.assert_called_once()
    
    # Verify the checklist content got injected into the prompt
    args, kwargs = model_router.generate.call_args
    assert "Mistake Avoidance Checklist" in args[1]
    assert "Avoid using deprecated module" in args[1]
