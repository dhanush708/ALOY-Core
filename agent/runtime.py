import uuid
import logging
import asyncio
from datetime import datetime
from typing import Dict, Any, Optional, List

from database.connection import DatabaseConnectionPool
from agent.types import ExecutionContext, AgentSessionState, TaskStep, TaskStatus
from agent.context import ExecutionContextBuilder
from agent.registry import AgentRegistry
from agent.task_queue import AgentTaskQueue
from agent.lock import WorkspaceLockManager
from agent.snapshot import WorkspaceSnapshotManager
from agent.journal import ExecutionJournalWriter
from agent.metrics import RuntimeMetricsCollector
from agent.fsm import AgentSessionFSM, InvalidStateTransitionError
from agent.checkpoint_resume import CheckpointResumeManager
from project.manager import ProjectManager
from models.router import ModelRouter
from kernel.types import Event, AGENT_SESSION_PAUSED, AGENT_SESSION_RESUMED, AGENT_SESSION_ROLLED_BACK

logger = logging.getLogger(__name__)


class AgentRuntime:
    """
    AgentRuntime is the top-level state machine coordinator of the Agent Core.
    It manages sessions, starts background manager tasks, and processes interrupts.
    """

    def __init__(
        self,
        db_pool: DatabaseConnectionPool,
        registry: AgentRegistry,
        task_queue: AgentTaskQueue,
        lock_manager: WorkspaceLockManager,
        snapshot_manager: WorkspaceSnapshotManager,
        journal_writer: ExecutionJournalWriter,
        metrics_collector: RuntimeMetricsCollector,
        project_manager: ProjectManager,
        model_router: ModelRouter,
        tool_system,
        event_bus,
    ):
        self.db_pool = db_pool
        self.registry = registry
        self.task_queue = task_queue
        self.lock_manager = lock_manager
        self.snapshot_manager = snapshot_manager
        self.journal_writer = journal_writer
        self.metrics = metrics_collector
        self.project_manager = project_manager
        self.model_router = model_router
        self.tool_system = tool_system
        self.event_bus = event_bus

        self.fsm = AgentSessionFSM(db_pool)
        self.checkpoint_resume = CheckpointResumeManager(db_pool, task_queue, snapshot_manager)

        self._active_contexts: Dict[str, ExecutionContext] = {}
        self._active_tasks: Dict[str, asyncio.Task] = {}


    async def start_session(self, goal: str, project_id: Optional[str] = None) -> str:
        """Create a new agent session and initialize it in the database."""
        session_id = str(uuid.uuid4())
        now = datetime.utcnow().isoformat()

        # Retrieve project path and manifest (project is optional)
        workspace_path = ""
        manifest = {}
        if project_id:
            project = self.project_manager.get_project(project_id)
            if not project:
                raise ValueError(f"Project with ID '{project_id}' not found.")
            workspace_path = project["root_path"]
            manifest = project.get("metadata", {}).get("manifest", {})

        # Build execution context
        context = ExecutionContextBuilder.build(
            session_id=session_id,
            project_id=project_id or "",
            goal=goal,
            workspace_path=workspace_path,
            manifest=manifest,
        )
        self._active_contexts[session_id] = context

        # Insert session into SQLite
        with self.db_pool.get_write_connection() as conn:
            conn.execute(
                """
                INSERT INTO agent_sessions (id, project_id, goal, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (session_id, project_id, goal, AgentSessionState.PLANNING.value, now, now),
            )

        logger.info("Created agent session: %s", session_id)
        return session_id


    async def execute_session(self, session_id: str) -> None:
        """Spawn the ManagerAgent loop for the session as a background task."""
        if session_id in self._active_tasks and not self._active_tasks[session_id].done():
            logger.warning("Session %s is already executing.", session_id)
            return

        context = self._active_contexts.get(session_id)
        if not context:
            # Reconstruct context if not in memory
            with self.db_pool.get_read_connection() as conn:
                row = conn.execute("SELECT project_id, goal FROM agent_sessions WHERE id = ?", (session_id,)).fetchone()
            if not row:
                raise KeyError(f"Session '{session_id}' not found in DB.")
            project_id, goal = row
            project = self.project_manager.get_project(project_id)
            workspace_path = project["root_path"] if project else ""
            manifest = project.get("metadata", {}).get("manifest", {}) if project else {}

            context = ExecutionContextBuilder.build(
                session_id=session_id,
                project_id=project_id,
                goal=goal,
                workspace_path=workspace_path,
                manifest=manifest,
            )
            self._active_contexts[session_id] = context

        # Initialize metrics
        self.metrics.start_session(session_id)

        # Retrieve manager
        manager = self.registry.get("manager")

        # Run orchestrator
        async def run_and_finalize():
            try:
                await manager.run(session_id, context, self.tool_system, self.model_router)
            finally:
                # Generate execution journal upon completion or failure
                try:
                    await self.journal_writer.generate_journal(session_id, context.workspace_path)
                except Exception as journal_err:
                    logger.error("Failed to generate journal: %s", journal_err)

        task = asyncio.create_task(run_and_finalize())
        self._active_tasks[session_id] = task

    async def pause_session(self, session_id: str) -> None:
        """Pause execution of the session."""
        context = self._active_contexts.get(session_id)
        await self.fsm.transition_to(session_id, AgentSessionState.PAUSED)

        # Pause tasks in the queue
        await self.task_queue.pause_session(session_id)

        await self.event_bus.publish(
            Event(
                type=AGENT_SESSION_PAUSED,
                data={"session_id": session_id},
                source="agent_runtime",
            )
        )
        logger.info("Paused agent session: %s", session_id)

    async def resume_session(self, session_id: str) -> None:
        """Resume execution of a paused session."""
        context = self._active_contexts.get(session_id)
        # Resuming transitions state back to EXECUTING
        await self.fsm.transition_to(session_id, AgentSessionState.EXECUTING)

        # Resume tasks in the queue
        await self.task_queue.resume_session(session_id)

        # Re-trigger executor task if it died or wasn't running
        if session_id not in self._active_tasks or self._active_tasks[session_id].done():
            await self.execute_session(session_id)

        await self.event_bus.publish(
            Event(
                type=AGENT_SESSION_RESUMED,
                data={"session_id": session_id},
                source="agent_runtime",
            )
        )
        logger.info("Resumed agent session: %s", session_id)

    async def cancel_session(self, session_id: str) -> None:
        """Cancel/terminate a session."""
        context = self._active_contexts.get(session_id)
        if context:
            context.cancellation_token.set()

        # Cancel tasks in task queue
        await self.task_queue.cancel_session(session_id)

        # Cancel active runner task
        task = self._active_tasks.get(session_id)
        if task and not task.done():
            task.cancel()

        await self.fsm.transition_to(session_id, AgentSessionState.FAILED)
        logger.info("Cancelled agent session: %s", session_id)

    async def rollback_session(self, session_id: str, checkpoint_id: str) -> None:
        """Restores the workspace state to the snapshot taken at checkpoint_id."""
        with self.db_pool.get_read_connection() as conn:
            row = conn.execute(
                "SELECT snapshot_path, step_index FROM agent_checkpoints WHERE id = ? AND session_id = ?",
                (checkpoint_id, session_id),
            ).fetchone()

        if not row:
            raise KeyError(f"Checkpoint '{checkpoint_id}' not found for session '{session_id}'.")

        snapshot_path, step_index = row

        # Fetch workspace path
        with self.db_pool.get_read_connection() as conn:
            ws_row = conn.execute(
                "SELECT root_path FROM projects WHERE id = (SELECT project_id FROM agent_sessions WHERE id = ?)",
                (session_id,),
            ).fetchone()

        if not ws_row:
            raise KeyError(f"Workspace path not found for session '{session_id}'.")

        workspace_path = ws_row[0]

        # 1. Rollback snapshot
        await self.snapshot_manager.restore_snapshot(workspace_path, snapshot_path)

        # 2. Transition state and reset plan step index
        await self.fsm.transition_to(session_id, AgentSessionState.ROLLED_BACK)
        with self.db_pool.get_write_connection() as conn:
            conn.execute(
                "UPDATE agent_plans SET current_step_index = ? WHERE session_id = ?",
                (step_index, session_id),
            )

        await self.event_bus.publish(
            Event(
                type=AGENT_SESSION_ROLLED_BACK,
                data={"session_id": session_id, "checkpoint_id": checkpoint_id},
                source="agent_runtime",
            )
        )
        logger.info("Rolled back agent session %s to checkpoint %s", session_id, checkpoint_id)

    async def resume_session_from_checkpoint(self, session_id: str, checkpoint_id: str) -> None:
        """Restores workspace and resets state to resume from a specific checkpoint."""
        with self.db_pool.get_read_connection() as conn:
            ws_row = conn.execute(
                "SELECT root_path FROM projects WHERE id = (SELECT project_id FROM agent_sessions WHERE id = ?)",
                (session_id,),
            ).fetchone()

        if not ws_row:
            raise KeyError(f"Workspace path not found for session '{session_id}'.")

        workspace_path = ws_row[0]

        # 1. Reset database state, task status, and restore files
        await self.checkpoint_resume.resume_from_checkpoint(session_id, checkpoint_id, workspace_path)

        # 2. Trigger execution loop again
        await self.execute_session(session_id)


    async def get_session_status(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get session details and execution status."""
        with self.db_pool.get_read_connection() as conn:
            row = conn.execute(
                "SELECT id, project_id, goal, status, created_at, updated_at, metadata FROM agent_sessions WHERE id = ?",
                (session_id,),
            ).fetchone()

        if not row:
            return None

        # Count tasks
        tasks = await self.task_queue.list_tasks(session_id)
        task_stats = {
            "total": len(tasks),
            "pending": len([t for t in tasks if t.status == TaskStatus.PENDING]),
            "running": len([t for t in tasks if t.status == TaskStatus.RUNNING]),
            "done": len([t for t in tasks if t.status == TaskStatus.DONE]),
            "failed": len([t for t in tasks if t.status == TaskStatus.FAILED]),
        }

        # Checkpoints
        with self.db_pool.get_read_connection() as conn:
            checkpoints = conn.execute(
                "SELECT id, step_index, created_at FROM agent_checkpoints WHERE session_id = ? ORDER BY step_index",
                (session_id,),
            ).fetchall()

        checkpoint_list = [{"id": r[0], "step_index": r[1], "created_at": r[2]} for r in checkpoints]

        return {
            "session_id": row[0],
            "project_id": row[1],
            "goal": row[2],
            "status": row[3],
            "created_at": row[4],
            "updated_at": row[5],
            "metadata": row[6],
            "tasks": task_stats,
            "checkpoints": checkpoint_list,
        }
