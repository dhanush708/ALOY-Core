import json
import logging
from datetime import datetime
from agent.types import TaskStatus, AgentSessionState
from agent.task_queue import AgentTaskQueue
from agent.snapshot import WorkspaceSnapshotManager
from database.connection import DatabaseConnectionPool

logger = logging.getLogger(__name__)


class CheckpointResumeManager:
    """Manages restoring and resuming agent session states from checkpoints."""

    def __init__(
        self,
        db_pool: DatabaseConnectionPool,
        task_queue: AgentTaskQueue,
        snapshot_manager: WorkspaceSnapshotManager,
    ):
        self.db_pool = db_pool
        self.task_queue = task_queue
        self.snapshot_manager = snapshot_manager

    async def resume_from_checkpoint(self, session_id: str, checkpoint_id: str, workspace_path: str) -> None:
        """Restores workspace and resets the task queue to resume execution."""
        logger.info("Resuming session %s from checkpoint %s", session_id, checkpoint_id)

        # 1. Fetch checkpoint details
        with self.db_pool.get_read_connection() as conn:
            checkpoint_row = conn.execute(
                "SELECT step_index, snapshot_path, state_data FROM agent_checkpoints WHERE id = ? AND session_id = ?",
                (checkpoint_id, session_id),
            ).fetchone()

        if not checkpoint_row:
            raise KeyError(f"Checkpoint '{checkpoint_id}' not found for session '{session_id}'.")

        step_index, snapshot_path, state_data_str = checkpoint_row

        # 2. Restore workspace snapshot
        await self.snapshot_manager.restore_snapshot(workspace_path, snapshot_path)

        # 3. Clean up and reset database states
        now = datetime.utcnow().isoformat()
        with self.db_pool.get_write_connection() as conn:
            # Revert step index
            conn.execute(
                "UPDATE agent_plans SET current_step_index = ? WHERE session_id = ?",
                (step_index, session_id),
            )
            # Revert session state back to planning or executing
            target_status = AgentSessionState.PLANNING.value if step_index == 0 else AgentSessionState.EXECUTING.value
            conn.execute(
                "UPDATE agent_sessions SET status = ?, updated_at = ? WHERE id = ?",
                (target_status, now, session_id),
            )

        # Reset task queue states
        with self.db_pool.get_write_connection() as conn:
            conn.execute(
                """
                UPDATE agent_tasks 
                SET status = 'pending', retry_count = 0, error = NULL, result = NULL 
                WHERE session_id = ? AND status IN ('running', 'failed', 'paused', 'cancelled')
                """,
                (session_id,),
            )

        logger.info("Successfully reset task queue and session state for resume.")
