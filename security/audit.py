import logging
import json
from datetime import datetime, timezone
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

class AuditLogger:
    """Append-only structured audit logging."""
    
    def __init__(self, db_pool):
        self.db_pool = db_pool
        
    async def start(self):
        logger.info("Security Audit Logger started.")
        
    async def stop(self):
        pass
        
    async def log_action(
        self,
        actor: str,
        action: str,
        target: str,
        status: str,
        details: Optional[Dict[str, Any]] = None
    ):
        """Log an action to the audit trail."""
        timestamp = datetime.now(timezone.utc).isoformat()
        details_json = json.dumps(details) if details else "{}"
        
        try:
            with self.db_pool.get_write_connection() as conn:
                conn.execute(
                    """
                    INSERT INTO audit_log (actor, action, target, status, timestamp, details)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (actor, action, target, status, timestamp, details_json)
                )
            logger.debug(f"Audit log: {actor} {action} {target} -> {status}")
        except Exception as e:
            # We must not let audit logging failures crash the system, but we should log them heavily
            logger.critical(f"Failed to write to audit log! Data: {actor} {action} {target}. Error: {e}")
