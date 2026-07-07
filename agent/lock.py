import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from database.connection import DatabaseConnectionPool
from kernel.types import Event, WORKSPACE_LOCKED, WORKSPACE_UNLOCKED

logger = logging.getLogger(__name__)


class WorkspaceLockManager:
    """Manages exclusive workspace locks using sqlite and broadcasts lock state via the Event Bus."""

    def __init__(self, db_pool: DatabaseConnectionPool, event_bus):
        self.db_pool = db_pool
        self.event_bus = event_bus

    def _normalize_path(self, workspace_path: str) -> str:
        return str(Path(workspace_path).resolve().as_posix())

    async def acquire(self, workspace_path: str, session_id: str, ttl_minutes: int = 60) -> bool:
        """
        Attempts to acquire a lock on the workspace for a session.
        Returns True if successful, False if already locked.
        """
        normalized_path = self._normalize_path(workspace_path)
        now = datetime.now(timezone.utc)
        expires_at = (now + timedelta(minutes=ttl_minutes)).isoformat()
        now_str = now.isoformat()

        with self.db_pool.get_write_connection() as conn:
            # Check if there is an active (non-expired) lock
            row = conn.execute(
                "SELECT session_id, expires_at FROM workspace_locks WHERE workspace_path = ?",
                (normalized_path,),
            ).fetchone()

            if row:
                holder_session, expires_str = row
                expires = datetime.fromisoformat(expires_str)
                if expires > now:
                    # Still active lock held by another session
                    if holder_session == session_id:
                        # Re-acquire/refresh lock
                        conn.execute(
                            "UPDATE workspace_locks SET expires_at = ? WHERE workspace_path = ?",
                            (expires_at, normalized_path),
                        )
                        return True
                    logger.warning(
                        "Workspace '%s' is locked by active session '%s' until %s",
                        normalized_path,
                        holder_session,
                        expires_str,
                    )
                    return False
                else:
                    # Expired lock, delete it
                    conn.execute("DELETE FROM workspace_locks WHERE workspace_path = ?", (normalized_path,))

            # Create new lock
            conn.execute(
                """
                INSERT OR REPLACE INTO workspace_locks (workspace_path, session_id, acquired_at, expires_at)
                VALUES (?, ?, ?, ?)
                """,
                (normalized_path, session_id, now_str, expires_at),
            )

        # Broadcast lock event
        await self.event_bus.publish(
            Event(
                type=WORKSPACE_LOCKED,
                data={
                    "workspace_path": normalized_path,
                    "session_id": session_id,
                    "expires_at": expires_at,
                },
                source="workspace_lock_manager",
            )
        )
        return True

    async def release(self, workspace_path: str, session_id: str) -> None:
        """Release the lock on the workspace if held by the given session."""
        normalized_path = self._normalize_path(workspace_path)

        with self.db_pool.get_write_connection() as conn:
            # Confirm if the lock belongs to the requesting session before releasing
            row = conn.execute(
                "SELECT session_id FROM workspace_locks WHERE workspace_path = ?",
                (normalized_path,),
            ).fetchone()

            if row and row[0] == session_id:
                conn.execute("DELETE FROM workspace_locks WHERE workspace_path = ?", (normalized_path,))
            else:
                return

        # Broadcast unlock event
        await self.event_bus.publish(
            Event(
                type=WORKSPACE_UNLOCKED,
                data={
                    "workspace_path": normalized_path,
                    "session_id": session_id,
                },
                source="workspace_lock_manager",
            )
        )

    async def is_locked(self, workspace_path: str) -> bool:
        """Check if workspace is locked by an active session."""
        normalized_path = self._normalize_path(workspace_path)
        now = datetime.now(timezone.utc)

        with self.db_pool.get_read_connection() as conn:
            row = conn.execute(
                "SELECT expires_at FROM workspace_locks WHERE workspace_path = ?",
                (normalized_path,),
            ).fetchone()

        if row:
            expires = datetime.fromisoformat(row[0])
            return expires > now
        return False

    async def force_expire_stale_locks(self) -> None:
        """Force release all expired locks. Called during runtime boot."""
        now = datetime.now(timezone.utc).isoformat()
        with self.db_pool.get_write_connection() as conn:
            conn.execute("DELETE FROM workspace_locks WHERE expires_at <= ?", (now,))
