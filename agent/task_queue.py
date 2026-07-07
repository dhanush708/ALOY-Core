import json
import uuid
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional
from database.connection import DatabaseConnectionPool
from agent.types import TaskStep, TaskStatus

logger = logging.getLogger(__name__)


class AgentTaskQueue:
    """DB-backed task queue with dependency resolution, retry count tracking, and pause/resume."""

    def __init__(self, db_pool: DatabaseConnectionPool):
        self.db_pool = db_pool

    async def create_task(
        self,
        session_id: str,
        assigned_agent: str,
        title: str,
        description: str,
        parent_task_id: Optional[str] = None,
        priority: int = 5,
        depends_on: Optional[List[str]] = None,
        max_retries: int = 3,
        metadata: Optional[Dict[str, Any]] = None,
        task_id: Optional[str] = None,
    ) -> TaskStep:
        """Create a new task and insert it into the database."""
        if not task_id:
            task_id = str(uuid.uuid4())
        now = datetime.utcnow().isoformat()
        depends_on_list = depends_on or []
        metadata_dict = metadata or {}

        task = TaskStep(
            id=task_id,
            session_id=session_id,
            assigned_agent=assigned_agent,
            title=title,
            description=description,
            parent_task_id=parent_task_id,
            priority=priority,
            status=TaskStatus.PENDING,
            retry_count=0,
            max_retries=max_retries,
            depends_on=depends_on_list,
            created_at=now,
            updated_at=now,
            metadata=metadata_dict,
        )

        with self.db_pool.get_write_connection() as conn:
            conn.execute(
                """
                INSERT INTO agent_tasks (
                    id, session_id, parent_task_id, assigned_agent, title, description,
                    priority, status, retry_count, max_retries, depends_on, created_at, updated_at, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task.id,
                    task.session_id,
                    task.parent_task_id,
                    task.assigned_agent,
                    task.title,
                    task.description,
                    task.priority,
                    task.status.value,
                    task.retry_count,
                    task.max_retries,
                    json.dumps(task.depends_on),
                    task.created_at,
                    task.updated_at,
                    json.dumps(task.metadata),
                ),
            )

        return task

    async def get_next_task(self, session_id: str) -> Optional[TaskStep]:
        """
        Get the next runnable task. A task is runnable if:
        - status is PENDING
        - all tasks listed in depends_on are DONE
        Ordered by priority (1 is highest) and created_at.
        """
        with self.db_pool.get_read_connection() as conn:
            # First, check if session is paused or has any failed/cancelled tasks that block execution
            # Wait, is the session status paused? We check agent_sessions table status
            session_row = conn.execute(
                "SELECT status FROM agent_sessions WHERE id = ?", (session_id,)
            ).fetchone()
            if session_row and session_row[0] in ("paused", "failed", "completed", "cancelled"):
                return None

            # Retrieve all tasks for the session to resolve dependencies
            rows = conn.execute(
                """
                SELECT id, session_id, parent_task_id, assigned_agent, title, description,
                       priority, status, retry_count, max_retries, depends_on, result, error,
                       created_at, updated_at, metadata
                FROM agent_tasks
                WHERE session_id = ?
                """,
                (session_id,),
            ).fetchall()

        if not rows:
            return None

        # Build map of task_id -> status and task_id -> TaskStep
        tasks: Dict[str, TaskStep] = {}
        for r in rows:
            depends = json.loads(r[10]) if r[10] else []
            meta = json.loads(r[15]) if r[15] else {}
            tasks[r[0]] = TaskStep(
                id=r[0],
                session_id=r[1],
                parent_task_id=r[2],
                assigned_agent=r[3],
                title=r[4],
                description=r[5],
                priority=r[6],
                status=TaskStatus(r[7]),
                retry_count=r[8],
                max_retries=r[9],
                depends_on=depends,
                result=r[11],
                error=r[12],
                created_at=r[13],
                updated_at=r[14],
                metadata=meta,
            )

        # Filter runnable tasks: status is PENDING and all depends_on tasks are DONE
        runnable_tasks: List[TaskStep] = []
        for t in tasks.values():
            if t.status == TaskStatus.PENDING:
                # Check dependencies
                deps_satisfied = True
                for dep_id in t.depends_on:
                    dep_task = tasks.get(dep_id)
                    if not dep_task or dep_task.status != TaskStatus.DONE:
                        deps_satisfied = False
                        break
                if deps_satisfied:
                    runnable_tasks.append(t)

        if not runnable_tasks:
            return None

        # Sort by priority ascending (1 first), then created_at ascending
        runnable_tasks.sort(key=lambda x: (x.priority, x.created_at))
        return runnable_tasks[0]

    async def mark_running(self, task_id: str) -> None:
        """Mark task as running."""
        now = datetime.utcnow().isoformat()
        with self.db_pool.get_write_connection() as conn:
            conn.execute(
                "UPDATE agent_tasks SET status = ?, updated_at = ? WHERE id = ?",
                (TaskStatus.RUNNING.value, now, task_id),
            )

    async def mark_done(self, task_id: str, result: Optional[str] = None) -> None:
        """Mark task as done."""
        now = datetime.utcnow().isoformat()
        with self.db_pool.get_write_connection() as conn:
            conn.execute(
                "UPDATE agent_tasks SET status = ?, result = ?, updated_at = ? WHERE id = ?",
                (TaskStatus.DONE.value, result, now, task_id),
            )

    async def mark_failed(self, task_id: str, error: Optional[str] = None) -> None:
        """Mark task as failed."""
        now = datetime.utcnow().isoformat()
        with self.db_pool.get_write_connection() as conn:
            conn.execute(
                "UPDATE agent_tasks SET status = ?, error = ?, updated_at = ? WHERE id = ?",
                (TaskStatus.FAILED.value, error, now, task_id),
            )

    async def retry_task(self, task_id: str) -> None:
        """Increment retry count and put task back to PENDING."""
        now = datetime.utcnow().isoformat()
        with self.db_pool.get_write_connection() as conn:
            conn.execute(
                """
                UPDATE agent_tasks 
                SET status = ?, retry_count = retry_count + 1, updated_at = ? 
                WHERE id = ?
                """,
                (TaskStatus.PENDING.value, now, task_id),
            )

    async def pause_session(self, session_id: str) -> None:
        """Pause all non-completed/non-failed tasks in the session."""
        now = datetime.utcnow().isoformat()
        with self.db_pool.get_write_connection() as conn:
            # We also update running/pending tasks in agent_tasks
            conn.execute(
                """
                UPDATE agent_tasks 
                SET status = ?, updated_at = ? 
                WHERE session_id = ? AND status IN (?, ?)
                """,
                (TaskStatus.PAUSED.value, now, session_id, TaskStatus.PENDING.value, TaskStatus.RUNNING.value),
            )

    async def resume_session(self, session_id: str) -> None:
        """Resume all paused tasks in the session."""
        now = datetime.utcnow().isoformat()
        with self.db_pool.get_write_connection() as conn:
            conn.execute(
                """
                UPDATE agent_tasks 
                SET status = ?, updated_at = ? 
                WHERE session_id = ? AND status = ?
                """,
                (TaskStatus.PENDING.value, now, session_id, TaskStatus.PAUSED.value),
            )

    async def cancel_session(self, session_id: str) -> None:
        """Cancel all pending, running, paused, or queued tasks."""
        now = datetime.utcnow().isoformat()
        with self.db_pool.get_write_connection() as conn:
            conn.execute(
                """
                UPDATE agent_tasks 
                SET status = ?, updated_at = ? 
                WHERE session_id = ? AND status IN (?, ?, ?, ?)
                """,
                (
                    TaskStatus.CANCELLED.value,
                    now,
                    session_id,
                    TaskStatus.PENDING.value,
                    TaskStatus.QUEUED.value,
                    TaskStatus.RUNNING.value,
                    TaskStatus.PAUSED.value,
                ),
            )

    async def list_tasks(self, session_id: str, status: Optional[TaskStatus] = None) -> List[TaskStep]:
        """List tasks for a session, optionally filtered by status."""
        query = """
            SELECT id, session_id, parent_task_id, assigned_agent, title, description,
                   priority, status, retry_count, max_retries, depends_on, result, error,
                   created_at, updated_at, metadata
            FROM agent_tasks
            WHERE session_id = ?
        """
        params = [session_id]
        if status:
            query += " AND status = ?"
            params.append(status.value)

        query += " ORDER BY priority, created_at"

        with self.db_pool.get_read_connection() as conn:
            rows = conn.execute(query, params).fetchall()

        tasks = []
        for r in rows:
            depends = json.loads(r[10]) if r[10] else []
            meta = json.loads(r[15]) if r[15] else {}
            tasks.append(
                TaskStep(
                    id=r[0],
                    session_id=r[1],
                    parent_task_id=r[2],
                    assigned_agent=r[3],
                    title=r[4],
                    description=r[5],
                    priority=r[6],
                    status=TaskStatus(r[7]),
                    retry_count=r[8],
                    max_retries=r[9],
                    depends_on=depends,
                    result=r[11],
                    error=r[12],
                    created_at=r[13],
                    updated_at=r[14],
                    metadata=meta,
                )
            )
        return tasks
