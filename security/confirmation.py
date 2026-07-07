import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, Any

from .policy import PolicyEngine, PolicyDecision
from .audit import AuditLogger

logger = logging.getLogger(__name__)

class ConfirmationWorkflow:
    """Handles user approval requests and session caching."""
    
    def __init__(self, policy_engine: PolicyEngine, audit_logger: AuditLogger, db_pool):
        self.policy = policy_engine
        self.audit = audit_logger
        self.db_pool = db_pool
        
    async def start(self):
        logger.info("Confirmation Workflow started.")
        
    async def stop(self):
        pass
        
    def _has_session_approval(self, session_id: str, action: str, target: str) -> bool:
        """Check if there is an active session approval for this action."""
        with self.db_pool.get_read_connection() as conn:
            cursor = conn.execute(
                """
                SELECT expires_at FROM session_approvals 
                WHERE session_id = ? AND action_pattern = ?
                """,
                (session_id, f"{action}:{target}")
            )
            row = cursor.fetchone()
            if row:
                expires_at = datetime.fromisoformat(row["expires_at"])
                if datetime.now(timezone.utc) < expires_at:
                    return True
        return False
        
    def _grant_session_approval(self, session_id: str, action: str, target: str, duration_hours: int = 1):
        """Grant session approval."""
        now = datetime.now(timezone.utc)
        expires_at = (now + timedelta(hours=duration_hours)).isoformat()
        
        with self.db_pool.get_write_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO session_approvals (session_id, action_pattern, approved_at, expires_at)
                VALUES (?, ?, ?, ?)
                """,
                (session_id, f"{action}:{target}", now.isoformat(), expires_at)
            )
            
    async def check_or_request_approval(
        self, 
        actor: str, 
        action: str, 
        target: str, 
        session_id: str,
        context: Dict[str, Any] = None
    ) -> bool:
        """
        Check if action is allowed. If it requires approval, check session or request from user.
        """
        ctx = context or {}
        ctx["actor"] = actor
        
        # 1. Evaluate policy
        decision = await self.policy.evaluate(action, target, ctx)
        
        if not decision.allowed and not decision.requires_approval:
            await self.audit.log_action(actor, action, target, "denied", {"reason": decision.reason})
            return False
            
        if decision.allowed and not decision.requires_approval:
            await self.audit.log_action(actor, action, target, "allowed", {"reason": decision.reason})
            return True
            
        # 2. Check session approvals
        if decision.auto_approve_for_session and self._has_session_approval(session_id, action, target):
            await self.audit.log_action(actor, action, target, "allowed", {"reason": "session_approved"})
            return True
            
        # 3. Request user approval (Mocked for now as returning True, in reality would use event bus / websockets)
        logger.warning(f"ACTION REQUIRES APPROVAL: {actor} wants to {action} on {target}.")
        # MOCK: Assume user approved
        user_approved = True 
        
        if user_approved:
            await self.audit.log_action(actor, action, target, "allowed", {"reason": "user_approved"})
            if decision.auto_approve_for_session:
                self._grant_session_approval(session_id, action, target)
            return True
        else:
            await self.audit.log_action(actor, action, target, "denied", {"reason": "user_rejected"})
            return False
