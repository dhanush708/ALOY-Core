import os
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

class Sandbox:
    """Path validation and workspace boundary enforcement."""
    
    def __init__(self, workspace_root: str, db_pool=None):
        self.workspace_root = Path(workspace_root).resolve()
        self.db_pool = db_pool
        
    def is_within_workspace(self, path: str) -> bool:
        """Check if a given path is within the allowed workspace root or any registered project root."""
        try:
            # Resolve resolves symlinks and standardizes path
            target_path = Path(path).resolve()
            
            # 1. Check if relative to workspace_root (server dir)
            if self.workspace_root in target_path.parents or target_path == self.workspace_root:
                return True
                
            # 2. Check if relative to any registered project root in database
            if self.db_pool:
                try:
                    with self.db_pool.get_read_connection() as conn:
                        rows = conn.execute("SELECT root_path FROM projects").fetchall()
                    for row in rows:
                        proj_root = Path(row[0]).resolve()
                        if proj_root in target_path.parents or target_path == proj_root:
                            return True
                except Exception as db_err:
                    logger.warning(f"Database lookup failed for sandbox check: {db_err}")
                    
            return False
        except Exception as e:
            logger.warning(f"Error checking sandbox boundary for {path}: {e}")
            return False
            
    def validate_path(self, path: str) -> str:
        """Validates path and returns the resolved path if safe, raises ValueError if not."""
        if not self.is_within_workspace(path):
            raise ValueError(f"Security violation: Path {path} is outside the workspace sandbox.")
        return str(Path(path).resolve())
