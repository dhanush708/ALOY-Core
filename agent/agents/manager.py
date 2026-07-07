import logging
import json
import asyncio
from datetime import datetime, timezone
from typing import Optional, Dict, Any

from database.connection import DatabaseConnectionPool
from agent.types import TaskStep, ExecutionContext, TaskResult, TaskStatus, AgentSessionState
from agent.agents.base import BaseAgent
from agent.task_queue import AgentTaskQueue
from agent.registry import AgentRegistry
from agent.lock import WorkspaceLockManager
from agent.snapshot import WorkspaceSnapshotManager
from kernel.types import (
    Event,
    AGENT_SESSION_STARTED,
    AGENT_SESSION_COMPLETED,
    AGENT_SESSION_FAILED,
    AGENT_SESSION_PAUSED,
    AGENT_SESSION_RESUMED,
    TASK_STARTED,
    TASK_COMPLETED,
    TASK_FAILED,
    TASK_RETRY,
    CHECKPOINT_CREATED,
)

logger = logging.getLogger(__name__)


class ManagerAgent(BaseAgent):
    """
    Manager Agent is the true orchestrator of the agent runtime.
    It drives the task execution loop, coordinates worker agents,
    handles retries and checkpoints, and tracks overall session progress.
    """

    def __init__(
        self,
        db_pool: DatabaseConnectionPool,
        task_queue: AgentTaskQueue,
        registry: AgentRegistry,
        lock_manager: WorkspaceLockManager,
        snapshot_manager: WorkspaceSnapshotManager,
        event_bus,
    ):
        self.db_pool = db_pool
        self.task_queue = task_queue
        self.registry = registry
        self.lock_manager = lock_manager
        self.snapshot_manager = snapshot_manager
        self.event_bus = event_bus

    @property
    def name(self) -> str:
        return "manager"

    @property
    def description(self) -> str:
        return "Coordinates workflow execution, monitors tasks, and manages agent checkpoints."

    async def execute(
        self,
        task: TaskStep,
        context: ExecutionContext,
        tool_system,
        model_router,
    ) -> TaskResult:
        # Implementing BaseAgent interface (Manager acts as its own driver)
        return TaskResult(success=True, result="Manager execution completed.")

    async def run(
        self,
        session_id: str,
        context: ExecutionContext,
        tool_system,
        model_router,
    ) -> None:
        """Main orchestrator loop for executing a session's plan."""
        logger.info("Manager starting orchestration for session: %s", session_id)
        
        # 1. Update session status to planning
        await self._update_session_state(session_id, AgentSessionState.PLANNING)
        await self.event_bus.publish(
            Event(
                type=AGENT_SESSION_STARTED,
                data={"session_id": session_id, "goal": context.goal},
                source="manager_agent",
            )
        )

        # 2. Check workspace lock
        locked = await self.lock_manager.acquire(context.workspace_path, session_id)
        if not locked:
            err_msg = f"Cannot start execution: workspace is locked by another session."
            await self._update_session_state(session_id, AgentSessionState.FAILED, error_msg=err_msg)
            await self.event_bus.publish(
                Event(
                    type=AGENT_SESSION_FAILED,
                    data={"session_id": session_id, "error": err_msg},
                    source="manager_agent",
                )
            )
            return

        try:
            # 3. Create initial planning task
            plan_task = await self.task_queue.create_task(
                session_id=session_id,
                assigned_agent="planner",
                title="Create Execution Plan",
                description=f"Decompose the main goal into specific task steps: {context.goal}",
                priority=1,
            )

            # 4. Main task processing loop
            while not context.cancellation_token.is_set():
                # Check current session state in DB
                state = await self._get_session_state(session_id)
                if state == AgentSessionState.PAUSED:
                    await asyncio.sleep(0.5)
                    continue

                task = await self.task_queue.get_next_task(session_id)
                if not task:
                    # Check if there are any active/running tasks or if we're completely done
                    all_tasks = await self.task_queue.list_tasks(session_id)
                    pending_or_running = [t for t in all_tasks if t.status in (TaskStatus.PENDING, TaskStatus.RUNNING, TaskStatus.QUEUED)]
                    if not pending_or_running:
                        # Everything completed successfully!
                        break
                    # Wait for tasks to be released or complete
                    await asyncio.sleep(0.5)
                    continue

                logger.info("Manager claiming task: %s (%s)", task.title, task.assigned_agent)
                await self.task_queue.mark_running(task.id)
                await self.event_bus.publish(
                    Event(
                        type=TASK_STARTED,
                        data={"session_id": session_id, "task_id": task.id, "agent": task.assigned_agent},
                        source="manager_agent",
                    )
                )

                # Dynamically retrieve and run worker agent
                try:
                    agent = self.registry.get(task.assigned_agent)
                    context.current_task = task
                    
                    # Execute worker task
                    result = await agent.execute(task, context, tool_system, model_router)
                    
                    if result.success:
                        logger.info("Task completed successfully: %s", task.id)
                        await self.task_queue.mark_done(task.id, result.result)
                        await self.event_bus.publish(
                            Event(
                                type=TASK_COMPLETED,
                                data={"session_id": session_id, "task_id": task.id, "result": result.result},
                                source="manager_agent",
                            )
                        )

                        # If planning completed, switch session to executing state
                        if task.id == plan_task.id:
                            await self._update_session_state(session_id, AgentSessionState.EXECUTING)
                            
                            # Parse planner results into agent_plans table
                            try:
                                steps_data = json.loads(result.result) if result.result else []
                                await self._store_agent_plan(session_id, steps_data)
                                
                                # Enqueue the steps into the task queue
                                id_mapping = {}
                                for step in steps_data:
                                    planner_id = step.get("id")
                                    if planner_id:
                                        id_mapping[planner_id] = f"{session_id}_{planner_id}"
                                
                                for step in steps_data:
                                    planner_id = step.get("id")
                                    if not planner_id:
                                        continue
                                    
                                    db_id = id_mapping[planner_id]
                                    assigned_agent = step.get("assigned_agent")
                                    title = step.get("title", f"Task {planner_id}")
                                    description = step.get("description", "")
                                    
                                    # Map dependencies
                                    depends_on_raw = step.get("depends_on") or []
                                    depends_on_mapped = [id_mapping[dep] for dep in depends_on_raw if dep in id_mapping]
                                    
                                    priority = step.get("priority", 5)
                                    
                                    await self.task_queue.create_task(
                                        session_id=session_id,
                                        assigned_agent=assigned_agent,
                                        title=title,
                                        description=description,
                                        priority=priority,
                                        depends_on=depends_on_mapped,
                                        task_id=db_id
                                    )
                                logger.info("Successfully enqueued %d steps for session %s", len(steps_data), session_id)
                            except Exception as plan_err:
                                logger.warning("Could not store plan details or enqueue tasks: %s", plan_err)

                        # Checkpoint at key milestones (after planner, coder, or tester)
                        if task.assigned_agent in ("planner", "coder", "tester"):
                            await self._create_checkpoint(session_id, context)

                    else:
                        raise Exception(result.error or "Unknown task failure")

                except Exception as e:
                    logger.error("Task failed: %s. Error: %s", task.id, e)
                    
                    # Handle retries
                    if task.retry_count < task.max_retries:
                        await self.task_queue.retry_task(task.id)
                        await self.event_bus.publish(
                            Event(
                                type=TASK_RETRY,
                                data={"session_id": session_id, "task_id": task.id, "retry_count": task.retry_count + 1},
                                source="manager_agent",
                            )
                        )
                    else:
                        # Max retries exceeded
                        await self.task_queue.mark_failed(task.id, str(e))
                        await self.event_bus.publish(
                            Event(
                                type=TASK_FAILED,
                                data={"session_id": session_id, "task_id": task.id, "error": str(e)},
                                source="manager_agent",
                            )
                        )

                        # Escalation: trigger DebugAgent if coder/tester failed
                        if task.assigned_agent in ("coder", "tester"):
                            logger.info("Escalating failure to debug agent...")
                            debug_task = await self.task_queue.create_task(
                                session_id=session_id,
                                assigned_agent="debugger",
                                title=f"Debug failure of: {task.title}",
                                description=f"Analyze error: {e}",
                                priority=2,
                            )
                            # Create new coding/testing tasks that depend on debugger task
                            continue

                        # General failure exit
                        await self._update_session_state(session_id, AgentSessionState.FAILED, error_msg=str(e))
                        await self.event_bus.publish(
                            Event(
                                type=AGENT_SESSION_FAILED,
                                data={"session_id": session_id, "error": str(e)},
                                source="manager_agent",
                            )
                        )
                        return

            if context.cancellation_token.is_set():
                logger.info("Session cancelled: %s", session_id)
                await self.task_queue.cancel_session(session_id)
                await self._update_session_state(session_id, AgentSessionState.FAILED, error_msg="Cancelled by user")
                return

            # 5. Success exit
            # Run final documentation and learning agents
            await self._run_completion_agents(session_id, context, tool_system, model_router)
            await self._update_session_state(session_id, AgentSessionState.COMPLETED)
            await self.event_bus.publish(
                Event(
                    type=AGENT_SESSION_COMPLETED,
                    data={"session_id": session_id},
                    source="manager_agent",
                )
            )

        finally:
            # Release workspace lock
            await self.lock_manager.release(context.workspace_path, session_id)

    async def _update_session_state(self, session_id: str, state: AgentSessionState, error_msg: Optional[str] = None) -> None:
        now = datetime.utcnow().isoformat()
        metadata_dict = {"error": error_msg} if error_msg else {}
        with self.db_pool.get_write_connection() as conn:
            conn.execute(
                "UPDATE agent_sessions SET status = ?, updated_at = ?, metadata = ? WHERE id = ?",
                (state.value, now, json.dumps(metadata_dict), session_id),
            )

    async def _get_session_state(self, session_id: str) -> AgentSessionState:
        with self.db_pool.get_read_connection() as conn:
            row = conn.execute("SELECT status FROM agent_sessions WHERE id = ?", (session_id,)).fetchone()
        return AgentSessionState(row[0]) if row else AgentSessionState.FAILED

    async def _store_agent_plan(self, session_id: str, steps: list) -> None:
        now = datetime.utcnow().isoformat()
        plan_id = f"plan_{session_id}"
        with self.db_pool.get_write_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO agent_plans (id, session_id, steps, current_step_index, created_at)
                VALUES (?, ?, ?, 0, ?)
                """,
                (plan_id, session_id, json.dumps(steps), now),
            )

    async def _create_checkpoint(self, session_id: str, context: ExecutionContext) -> None:
        """Create workspace snapshot and save checkpoint metadata in SQLite."""
        try:
            snapshot_ref = await self.snapshot_manager.create_snapshot(context.workspace_path, session_id)
            
            # Find current step index
            step_idx = 0
            with self.db_pool.get_read_connection() as conn:
                row = conn.execute("SELECT current_step_index FROM agent_plans WHERE session_id = ?", (session_id,)).fetchone()
                if row:
                    step_idx = row[0]

            checkpoint_id = f"chk_{session_id}_{step_idx}_{int(datetime.utcnow().timestamp())}"
            now = datetime.utcnow().isoformat()

            # State payload
            state_data = json.dumps({
                "session_id": session_id,
                "step_index": step_idx,
                "timestamp": now,
            })

            with self.db_pool.get_write_connection() as conn:
                conn.execute(
                    """
                    INSERT INTO agent_checkpoints (id, session_id, step_index, snapshot_path, state_data, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (checkpoint_id, session_id, step_idx, snapshot_ref, state_data, now),
                )

            await self.event_bus.publish(
                Event(
                    type=CHECKPOINT_CREATED,
                    data={"session_id": session_id, "checkpoint_id": checkpoint_id, "snapshot_path": snapshot_ref},
                    source="manager_agent",
                )
            )
        except Exception as e:
            logger.error("Failed to create checkpoint: %s", e)

    async def _run_completion_agents(self, session_id: str, context: ExecutionContext, tool_system, model_router) -> None:
        """Runs documentation and learning agents directly at the end of a successful session."""
        for agent_name in ("documenter", "learner"):
            try:
                agent = self.registry.get(agent_name)
                task = TaskStep(
                    id=f"{agent_name}_{session_id}",
                    session_id=session_id,
                    assigned_agent=agent_name,
                    title=f"Finalizing session: {agent_name}",
                    description="Run session finalization steps",
                )
                await agent.execute(task, context, tool_system, model_router)
            except Exception as e:
                logger.error("Finalization agent %s failed: %s", agent_name, e)
