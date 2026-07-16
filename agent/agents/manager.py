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
            _running_tasks: Dict[str, asyncio.Task] = {}
            self._session_start_times = getattr(self, "_session_start_times", {})
            self._session_start_times[session_id] = datetime.utcnow()
            completed_durations = []

            while not context.cancellation_token.is_set():
                # Check current session state in DB
                state = await self._get_session_state(session_id)
                if state == AgentSessionState.PAUSED:
                    await asyncio.sleep(0.5)
                    continue

                # A. Clean up finished tasks from _running_tasks
                finished_ids = []
                for tid, t in list(_running_tasks.items()):
                    if t.done():
                        finished_ids.append(tid)
                        try:
                            t.result()
                        except Exception as e:
                            logger.error("Error in background execution task %s: %s", tid, e)
                for tid in finished_ids:
                    _running_tasks.pop(tid, None)

                # B. Check if we can launch more tasks
                max_parallel = 4
                while len(_running_tasks) < max_parallel:
                    task = await self.task_queue.get_next_task(session_id)
                    if not task:
                        break
                    
                    if task.id in _running_tasks:
                        break
                        
                    # Claim task immediately to prevent race conditions
                    await self.task_queue.mark_running(task.id)
                    await self.event_bus.publish(
                        Event(
                            type=TASK_STARTED,
                            data={"session_id": session_id, "task_id": task.id, "agent": task.assigned_agent},
                            source="manager_agent",
                        )
                    )
                    
                    _running_tasks[task.id] = asyncio.create_task(
                        self._execute_single_task(task, context, tool_system, model_router, completed_durations, plan_task)
                    )

                # C. Check if we are done
                all_tasks = await self.task_queue.list_tasks(session_id)
                pending_or_running = [t for t in all_tasks if t.status in (TaskStatus.PENDING, TaskStatus.RUNNING, TaskStatus.QUEUED)]
                
                if not _running_tasks and not pending_or_running:
                    # Double check if any pending are stuck because of failed dependencies
                    unrunnable_pending = [t for t in all_tasks if t.status == TaskStatus.PENDING]
                    if unrunnable_pending:
                        for pt in unrunnable_pending:
                            await self.task_queue.mark_failed(pt.id, "Unrunnable dependencies due to upstream failure")
                    break

                # D. Update progress metadata
                total_count = len(all_tasks)
                done_count = len([t for t in all_tasks if t.status == TaskStatus.DONE])
                failed_count = len([t for t in all_tasks if t.status == TaskStatus.FAILED])
                cancelled_count = len([t for t in all_tasks if t.status == TaskStatus.CANCELLED])
                
                pct = int(done_count / total_count * 100) if total_count > 0 else 0
                
                start_time = self._session_start_times.get(session_id, datetime.utcnow())
                elapsed = (datetime.utcnow() - start_time).total_seconds()
                
                remaining_count = total_count - (done_count + failed_count + cancelled_count)
                if completed_durations:
                    avg_dur = sum(completed_durations) / len(completed_durations)
                else:
                    avg_dur = 45.0
                eta = int(remaining_count * avg_dur)
                
                current_state_str = "Idle"
                current_model_str = "None"
                waiting_reason_str = "None"
                active_retry_count = 0
                
                active_tasks = [t for t in all_tasks if t.status == TaskStatus.RUNNING]
                if active_tasks:
                    current_state_str = f"Running: {active_tasks[0].title} ({active_tasks[0].assigned_agent})"
                    current_model_str = model_router.resolve_model("agent_coding" if active_tasks[0].assigned_agent == "coder" else "agent_planning")
                    active_retry_count = active_tasks[0].retry_count
                    
                    # If confirmation cache is waiting, set waiting reason
                    with self.db_pool.get_read_connection() as conn:
                        row = conn.execute(
                            "SELECT COUNT(*) FROM audit_log WHERE target LIKE ? AND status = 'pending'",
                            (f"%{session_id}%",)
                        ).fetchone()
                        if row and row[0] > 0:
                            waiting_reason_str = "Waiting for user approval of write/execute operation"
                
                progress_meta = {
                    "progress_pct": pct,
                    "elapsed_seconds": int(elapsed),
                    "eta_seconds": eta,
                    "current_state": current_state_str,
                    "waiting_reason": waiting_reason_str,
                    "current_model": current_model_str,
                    "retry_count": active_retry_count,
                    "completed_count": done_count,
                    "failed_count": failed_count,
                    "total_count": total_count
                }
                
                await self._update_session_progress_metadata(session_id, progress_meta)
                await asyncio.sleep(0.2)

            if context.cancellation_token.is_set():
                logger.info("Session cancelled: %s", session_id)
                await self.task_queue.cancel_session(session_id)
                await self._update_session_state(session_id, AgentSessionState.FAILED, error_msg="Cancelled by user")
                return

            # 5. Success/Failure exit
            all_tasks = await self.task_queue.list_tasks(session_id)
            has_failed_tasks = any(t.status == TaskStatus.FAILED for t in all_tasks)
            if has_failed_tasks:
                await self._update_session_state(session_id, AgentSessionState.FAILED, error_msg="One or more tasks failed.")
                await self.event_bus.publish(
                    Event(
                        type=AGENT_SESSION_FAILED,
                        data={"session_id": session_id, "error": "One or more tasks failed."},
                        source="manager_agent",
                    )
                )
            else:
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
            await self.lock_manager.release(context.workspace_path, session_id)

    async def _execute_single_task(
        self,
        task: TaskStep,
        context: ExecutionContext,
        tool_system,
        model_router,
        completed_durations: list,
        plan_task: TaskStep
    ) -> None:
        start_time = datetime.utcnow()
        session_id = task.session_id
        
        # Configure timeout: metadata or manifest or default to 300s
        timeout = task.metadata.get("timeout")
        if not timeout:
            timeout = context.manifest.get("project", {}).get("metadata", {}).get("task_timeout", 300)
            
        try:
            agent = self.registry.get(task.assigned_agent)
            context.current_task = task
            
            # Execute worker task with timeout wrapper
            result = await asyncio.wait_for(
                agent.execute(task, context, tool_system, model_router),
                timeout=timeout
            )
            
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
                
                duration = (datetime.utcnow() - start_time).total_seconds()
                completed_durations.append(duration)
                
                # If planning completed, switch session to executing state and enqueue subtasks
                if task.id == plan_task.id:
                    await self._update_session_state(session_id, AgentSessionState.EXECUTING)
                    try:
                        steps_data = json.loads(result.result) if result.result else []
                        await self._store_agent_plan(session_id, steps_data)
                        
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
                
                if task.assigned_agent in ("planner", "coder", "tester"):
                    await self._create_checkpoint(session_id, context)
            else:
                raise Exception(result.error or "Unknown task execution error")
                
        except asyncio.TimeoutError:
            logger.error("Task execution timed out: %s after %d seconds", task.id, timeout)
            await self._handle_task_failure(task, context, f"Task timed out after {timeout} seconds", tool_system, model_router)
        except Exception as e:
            logger.error("Task failed: %s. Error: %s", task.id, e)
            await self._handle_task_failure(task, context, str(e), tool_system, model_router)

    async def _handle_task_failure(
        self,
        task: TaskStep,
        context: ExecutionContext,
        error_msg: str,
        tool_system,
        model_router
    ) -> None:
        session_id = task.session_id
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
            await self.task_queue.mark_failed(task.id, error_msg)
            await self.event_bus.publish(
                Event(
                    type=TASK_FAILED,
                    data={"session_id": session_id, "task_id": task.id, "error": error_msg},
                    source="manager_agent",
                )
            )
            
            # Cancel all dependent tasks recursively so they don't block
            await self._cancel_dependent_tasks(session_id, task.id)
            
            if task.assigned_agent in ("coder", "tester"):
                logger.info("Escalating failure to debug agent...")
                try:
                    await self.task_queue.create_task(
                        session_id=session_id,
                        assigned_agent="debugger",
                        title=f"Debug failure of: {task.title}",
                        description=f"Analyze error: {error_msg}",
                        priority=2,
                    )
                except Exception as e:
                    logger.error("Failed to create debugger task: %s", e)

    async def _cancel_dependent_tasks(self, session_id: str, failed_task_id: str) -> None:
        """Finds all tasks in the session that depend on failed_task_id and cancels them recursively."""
        try:
            all_tasks = await self.task_queue.list_tasks(session_id)
            to_cancel = set()
            
            def find_deps(task_id):
                for t in all_tasks:
                    if task_id in t.depends_on and t.id not in to_cancel:
                        to_cancel.add(t.id)
                        find_deps(t.id)
                        
            find_deps(failed_task_id)
            
            now = datetime.utcnow().isoformat()
            if to_cancel:
                placeholders = ",".join("?" * len(to_cancel))
                with self.db_pool.get_write_connection() as conn:
                    conn.execute(
                        f"""
                        UPDATE agent_tasks 
                        SET status = ?, error = ?, updated_at = ? 
                        WHERE id IN ({placeholders})
                        """,
                        [TaskStatus.CANCELLED.value, f"Dependency task '{failed_task_id}' failed.", now] + list(to_cancel)
                    )
                for cid in to_cancel:
                    await self.event_bus.publish(
                        Event(
                            type=TASK_CANCELLED,
                            data={"session_id": session_id, "task_id": cid, "reason": f"Dependency task '{failed_task_id}' failed."},
                            source="manager_agent",
                        )
                    )
                logger.info("Cancelled dependent tasks due to failure of %s: %s", failed_task_id, to_cancel)
        except Exception as e:
            logger.error("Failed to cancel dependent tasks: %s", e)

    async def _update_session_progress_metadata(self, session_id: str, progress_meta: dict) -> None:
        now = datetime.utcnow().isoformat()
        try:
            with self.db_pool.get_read_connection() as conn:
                row = conn.execute("SELECT metadata FROM agent_sessions WHERE id = ?", (session_id,)).fetchone()
            
            meta = {}
            if row and row[0]:
                try:
                    meta = json.loads(row[0])
                except Exception:
                    pass
            
            meta.update(progress_meta)
            
            with self.db_pool.get_write_connection() as conn:
                conn.execute(
                    "UPDATE agent_sessions SET metadata = ?, updated_at = ? WHERE id = ?",
                    (json.dumps(meta), now, session_id),
                )
            
            await self.event_bus.publish(
                Event(
                    type=AGENT_STATE_CHANGED,
                    data={"session_id": session_id, "progress": progress_meta},
                    source="manager_agent",
                )
            )
        except Exception as e:
            logger.error("Failed to update session progress metadata: %s", e)

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
            
            step_idx = 0
            with self.db_pool.get_read_connection() as conn:
                row = conn.execute("SELECT current_step_index FROM agent_plans WHERE session_id = ?", (session_id,)).fetchone()
                if row:
                    step_idx = row[0]

            checkpoint_id = f"chk_{session_id}_{step_idx}_{int(datetime.utcnow().timestamp())}"
            now = datetime.utcnow().isoformat()

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
