import logging
from typing import Set, Dict
from agent.types import AgentSessionState
from database.connection import DatabaseConnectionPool

logger = logging.getLogger(__name__)


class InvalidStateTransitionError(ValueError):
    """Raised when an invalid state transition is attempted."""
    pass


VALID_TRANSITIONS: Dict[AgentSessionState, Set[AgentSessionState]] = {
    AgentSessionState.PLANNING: {
        AgentSessionState.EXECUTING,
        AgentSessionState.PAUSED,
        AgentSessionState.FAILED,
    },
    AgentSessionState.EXECUTING: {
        AgentSessionState.REVIEWING,
        AgentSessionState.PAUSED,
        AgentSessionState.FAILED,
        AgentSessionState.ROLLED_BACK,
    },
    AgentSessionState.REVIEWING: {
        AgentSessionState.COMPLETED,
        AgentSessionState.PAUSED,
        AgentSessionState.FAILED,
        AgentSessionState.ROLLED_BACK,
    },
    AgentSessionState.PAUSED: {
        AgentSessionState.PLANNING,
        AgentSessionState.EXECUTING,
        AgentSessionState.REVIEWING,
        AgentSessionState.FAILED,
    },
    AgentSessionState.COMPLETED: set(),  # terminal
    AgentSessionState.FAILED: {
        AgentSessionState.ROLLED_BACK,
    },
    AgentSessionState.ROLLED_BACK: {
        AgentSessionState.PLANNING,
        AgentSessionState.EXECUTING,
    },
}


class AgentSessionFSM:
    """Manages and enforces state transitions for agent sessions."""

    def __init__(self, db_pool: DatabaseConnectionPool):
        self.db_pool = db_pool

    async def get_state(self, session_id: str) -> AgentSessionState:
        with self.db_pool.get_read_connection() as conn:
            row = conn.execute("SELECT status FROM agent_sessions WHERE id = ?", (session_id,)).fetchone()
        if not row:
            raise KeyError(f"Session '{session_id}' not found.")
        return AgentSessionState(row[0])

    async def transition_to(self, session_id: str, target_state: AgentSessionState) -> None:
        """Transitions the session state, raising an error if the transition is invalid."""
        current_state = await self.get_state(session_id)
        if current_state == target_state:
            return  # NOP

        allowed = VALID_TRANSITIONS.get(current_state, set())
        if target_state not in allowed:
            raise InvalidStateTransitionError(
                f"Invalid transition from {current_state.value} to {target_state.value}"
            )

        import datetime
        now = datetime.datetime.utcnow().isoformat()
        with self.db_pool.get_write_connection() as conn:
            conn.execute(
                "UPDATE agent_sessions SET status = ?, updated_at = ? WHERE id = ?",
                (target_state.value, now, session_id),
            )
        logger.info("Session %s transitioned from %s to %s", session_id, current_state.value, target_state.value)
