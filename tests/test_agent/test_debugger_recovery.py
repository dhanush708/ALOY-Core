import asyncio
import os
import tempfile
import pytest
from unittest.mock import AsyncMock, MagicMock

from database.connection import DatabaseConnectionPool
from database.migrator import Migrator
from agent.task_queue import AgentTaskQueue
from agent.registry import AgentRegistry
from agent.lock import WorkspaceLockManager
from agent.snapshot import WorkspaceSnapshotManager
from agent.agents.manager import ManagerAgent
from agent.agents.debugger import DebugAgent
from agent.agents.base import BaseAgent
from agent.types import TaskStep, ExecutionContext, TaskResult, TaskStatus, AgentSessionState

class DummyPassAgent(BaseAgent):
    def __init__(self, name_str="coder"):
        self._name = name_str

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return "Dummy pass agent"

    async def execute(self, task, context, tool_system, model_router):
        return TaskResult(success=True, result="Pass result")

class FailThenPassTesterAgent(BaseAgent):
    def __init__(self):
        self.call_count = 0

    @property
    def name(self) -> str:
        return "tester"

    @property
    def description(self) -> str:
        return "Fails on initial run, passes on re-test"

    async def execute(self, task, context, tool_system, model_router):
        self.call_count += 1
        if task.metadata.get("is_repair"):
            return TaskResult(success=True, result="Tests passed after repair\nExit Code: 0")
        return TaskResult(success=False, error="AssertionError: 2 + 2 != 5\nExit Code: 1")

class AlwaysFailTesterAgent(BaseAgent):
    @property
    def name(self) -> str:
        return "tester"

    @property
    def description(self) -> str:
        return "Always fails"

    async def execute(self, task, context, tool_system, model_router):
        return TaskResult(success=False, error="Always failing tests\nExit Code: 1")

@pytest.mark.asyncio
async def test_debugger_recovery_success():
    """Verify that a genuine test failure triggers debugger recovery and completes only upon verified re-test."""
    temp_dir = tempfile.mkdtemp()
    db_path = os.path.join(temp_dir, "test.db")
    db_pool = DatabaseConnectionPool(db_path)
    try:
        migrator = Migrator(db_pool)
        await migrator.migrate()

        task_queue = AgentTaskQueue(db_pool)
        registry = AgentRegistry()
        event_bus = MagicMock()
        event_bus.publish = AsyncMock()
        lock_mgr = WorkspaceLockManager(db_pool, event_bus)
        snapshot_mgr = WorkspaceSnapshotManager()

        fail_then_pass_tester = FailThenPassTesterAgent()
        coder_agent = DummyPassAgent("coder")
        debugger_agent = DebugAgent()

        registry.register("tester", fail_then_pass_tester)
        registry.register("coder", coder_agent)
        registry.register("debugger", debugger_agent)

        session_id = "recovery_session_1"
        now = "2026-09-07T00:00:00"
        with db_pool.get_write_connection() as conn:
            conn.execute(
                "INSERT INTO projects (id, name, root_path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("proj_1", "Test Project", temp_dir, now, now)
            )
            conn.execute(
                "INSERT INTO agent_sessions (id, project_id, goal, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (session_id, "proj_1", "test recovery", AgentSessionState.PLANNING.value, now, now)
            )

        context = ExecutionContext(
            session_id=session_id,
            project_id="proj_1",
            goal="test recovery",
            workspace_path=temp_dir,
            manifest={},
            cancellation_token=asyncio.Event(),
        )

        manager = ManagerAgent(
            db_pool=db_pool,
            task_queue=task_queue,
            registry=registry,
            lock_manager=lock_mgr,
            snapshot_manager=snapshot_mgr,
            event_bus=event_bus,
        )

        mock_router = MagicMock()
        mock_router.generate = AsyncMock(return_value="Diagnosed issue: fix arithmetic logic.")
        mock_router.resolve_model = MagicMock(return_value="test_model")

        # Initial test task that fails with max_retries=1 so it triggers debugger
        initial_test_task = await task_queue.create_task(
            session_id=session_id,
            assigned_agent="tester",
            title="Run Unit Tests",
            description="Run initial tests",
            max_retries=1,
        )
        initial_test_task.retry_count = initial_test_task.max_retries

        # Trigger failure handling
        await manager._handle_task_failure(initial_test_task, context, "AssertionError: 2 + 2 != 5", None, mock_router)

        # Verify initial task remains FAILED (not falsely marked DONE)
        tasks = await task_queue.list_tasks(session_id)
        failed_orig = next(t for t in tasks if t.id == initial_test_task.id)
        assert failed_orig.status == TaskStatus.FAILED

        # Verify a debugger task was enqueued
        debug_task = next(t for t in tasks if t.assigned_agent == "debugger")
        assert debug_task is not None

        # Execute debugger task
        await manager._execute_single_task(debug_task, context, None, mock_router, [], initial_test_task)

        # After debugger finishes, repair task and re-test task should be created
        updated_tasks = await task_queue.list_tasks(session_id)
        repair_task = next((t for t in updated_tasks if t.assigned_agent == "coder" and t.metadata.get("is_repair")), None)
        retest_task = next((t for t in updated_tasks if t.assigned_agent == "tester" and t.metadata.get("is_repair")), None)
        assert repair_task is not None
        assert retest_task is not None

        # Execute repair task
        await manager._execute_single_task(repair_task, context, None, mock_router, [], initial_test_task)
        assert repair_task.id in [t.id for t in await task_queue.list_tasks(session_id) if t.status == TaskStatus.DONE]

        # Execute retest task (FailThenPassTesterAgent will succeed on is_repair)
        await manager._execute_single_task(retest_task, context, None, mock_router, [], initial_test_task)

        # Check final session evaluation
        final_tasks = await task_queue.list_tasks(session_id)
        repaired_ids = set()
        for t in final_tasks:
            if t.metadata.get("is_repair") and t.assigned_agent == "tester" and t.status == TaskStatus.DONE:
                rep_id = t.metadata.get("repaired_task_id")
                if rep_id:
                    repaired_ids.add(rep_id)

        has_unresolved_failures = False
        for t in final_tasks:
            if t.status == TaskStatus.FAILED:
                if t.id not in repaired_ids:
                    has_unresolved_failures = True
                    break

        # Verification: Original failure was resolved by successful retest
        assert has_unresolved_failures is False
        assert initial_test_task.id in repaired_ids
    finally:
        await db_pool.stop()
        import shutil
        shutil.rmtree(temp_dir, ignore_errors=True)

@pytest.mark.asyncio
async def test_debugger_recovery_false_success_prevention():
    """Verify that if tests continue to fail after repair, the session remains FAILED and never forces DONE."""
    temp_dir = tempfile.mkdtemp()
    db_path = os.path.join(temp_dir, "test.db")
    db_pool = DatabaseConnectionPool(db_path)
    try:
        migrator = Migrator(db_pool)
        await migrator.migrate()

        task_queue = AgentTaskQueue(db_pool)
        registry = AgentRegistry()
        event_bus = MagicMock()
        event_bus.publish = AsyncMock()
        lock_mgr = WorkspaceLockManager(db_pool, event_bus)
        snapshot_mgr = WorkspaceSnapshotManager()

        always_fail_tester = AlwaysFailTesterAgent()
        coder_agent = DummyPassAgent("coder")
        debugger_agent = DebugAgent()

        registry.register("tester", always_fail_tester)
        registry.register("coder", coder_agent)
        registry.register("debugger", debugger_agent)

        session_id = "false_success_session"
        now = "2026-09-07T00:00:00"
        with db_pool.get_write_connection() as conn:
            conn.execute(
                "INSERT INTO projects (id, name, root_path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("proj_1", "Test Project", temp_dir, now, now)
            )
            conn.execute(
                "INSERT INTO agent_sessions (id, project_id, goal, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (session_id, "proj_1", "intentional fail", AgentSessionState.PLANNING.value, now, now)
            )

        context = ExecutionContext(
            session_id=session_id,
            project_id="proj_1",
            goal="intentional fail",
            workspace_path=temp_dir,
            manifest={},
            cancellation_token=asyncio.Event(),
        )

        manager = ManagerAgent(
            db_pool=db_pool,
            task_queue=task_queue,
            registry=registry,
            lock_manager=lock_mgr,
            snapshot_manager=snapshot_mgr,
            event_bus=event_bus,
        )

        mock_router = MagicMock()
        mock_router.generate = AsyncMock(return_value="Fix attempt")
        mock_router.resolve_model = MagicMock(return_value="test_model")

        # Initial failing test task
        initial_test_task = await task_queue.create_task(
            session_id=session_id,
            assigned_agent="tester",
            title="Failing Tests",
            description="Run tests that intentionally fail",
            max_retries=1,
        )
        initial_test_task.retry_count = initial_test_task.max_retries

        await manager._handle_task_failure(initial_test_task, context, "Always failing tests", None, mock_router)

        tasks = await task_queue.list_tasks(session_id)
        debug_task = next(t for t in tasks if t.assigned_agent == "debugger")
        await manager._execute_single_task(debug_task, context, None, mock_router, [], initial_test_task)

        updated_tasks = await task_queue.list_tasks(session_id)
        repair_task = next(t for t in updated_tasks if t.assigned_agent == "coder" and t.metadata.get("is_repair"))
        retest_task = next(t for t in updated_tasks if t.assigned_agent == "tester" and t.metadata.get("is_repair"))

        # Repair executes
        await manager._execute_single_task(repair_task, context, None, mock_router, [], initial_test_task)
        # Retest executes and FAILS again
        retest_task.max_retries = 1
        retest_task.retry_count = retest_task.max_retries
        await manager._handle_task_failure(retest_task, context, "Still failing tests", None, mock_router)

        # Check resolution
        final_tasks = await task_queue.list_tasks(session_id)
        repaired_ids = set()
        for t in final_tasks:
            if t.metadata.get("is_repair") and t.assigned_agent == "tester" and t.status == TaskStatus.DONE:
                rep_id = t.metadata.get("repaired_task_id")
                if rep_id:
                    repaired_ids.add(rep_id)

        has_unresolved_failures = False
        for t in final_tasks:
            if t.status == TaskStatus.FAILED:
                if t.id not in repaired_ids:
                    has_unresolved_failures = True
                    break

        if any(t.status == TaskStatus.FAILED for t in final_tasks if t.metadata.get("is_repair")):
            has_unresolved_failures = True

        # CRITICAL ASSERTION: The session must remain FAILED, never force SUCCESS
        assert has_unresolved_failures is True
    finally:
        await db_pool.stop()
        import shutil
        shutil.rmtree(temp_dir, ignore_errors=True)
