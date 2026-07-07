import os
import shutil
import zipfile
import logging
import subprocess
from pathlib import Path
from typing import List, Dict, Any, Optional

from database.connection import DatabaseConnectionPool
from agent.snapshot import WorkspaceSnapshotManager

logger = logging.getLogger(__name__)

class AdvancedRollbackEngine:
    """
    Surgically rolls back individual files or directories to their state 
    recorded at a specific checkpoint (either git-based branch or zip archive).
    """

    def __init__(self, db_pool: DatabaseConnectionPool, snapshot_manager: WorkspaceSnapshotManager):
        self.db_pool = db_pool
        self.snapshot_manager = snapshot_manager

    def _is_git_repo(self, workspace_path: Path) -> bool:
        return (workspace_path / ".git").is_dir()

    def _run_git(self, workspace_path: Path, args: List[str]) -> str:
        res = subprocess.run(
            ["git"] + args,
            cwd=str(workspace_path),
            capture_output=True,
            text=True,
            check=True,
        )
        return res.stdout.strip()

    async def list_modified_files(self, session_id: str) -> List[str]:
        """Queries the agent task metadata to retrieve all files modified during a session."""
        files = set()
        with self.db_pool.get_read_connection() as conn:
            rows = conn.execute(
                "SELECT metadata FROM agent_tasks WHERE session_id = ?",
                (session_id,)
            ).fetchall()
            
        for row in rows:
            meta_str = row[0]
            if meta_str:
                import json
                try:
                    meta = json.loads(meta_str)
                    modified = meta.get("modified_files", [])
                    for f in modified:
                        files.add(f)
                except Exception:
                    pass
        return sorted(list(files))

    async def revert_single_file(self, session_id: str, checkpoint_id: str, file_path_str: str) -> bool:
        """
        Surgically restores a single file to its exact state at the given checkpoint.
        If the file did not exist at the checkpoint, it is safely deleted.
        """
        # 1. Fetch checkpoint details
        with self.db_pool.get_read_connection() as conn:
            chk_row = conn.execute(
                "SELECT snapshot_path FROM agent_checkpoints WHERE id = ? AND session_id = ?",
                (checkpoint_id, session_id),
            ).fetchone()

        if not chk_row:
            raise KeyError(f"Checkpoint '{checkpoint_id}' not found for session '{session_id}'.")

        snapshot_ref = chk_row[0]

        # 2. Fetch workspace path
        with self.db_pool.get_read_connection() as conn:
            ws_row = conn.execute(
                "SELECT root_path FROM projects WHERE id = (SELECT project_id FROM agent_sessions WHERE id = ?)",
                (session_id,),
            ).fetchone()

        if not ws_row:
            raise KeyError(f"Workspace path not found for session '{session_id}'.")

        workspace_path = Path(ws_row[0]).resolve()
        target_file = Path(file_path_str).resolve()

        # Security check: Ensure file is inside the workspace boundaries
        try:
            relative_file = target_file.relative_to(workspace_path).as_posix()
        except ValueError:
            logger.warning(f"Security violation: path traversal attempt in rollback for {file_path_str}")
            raise PermissionError(f"Access denied: file '{file_path_str}' is outside workspace boundaries.")

        # 3. Perform Reversion
        if snapshot_ref.startswith("git:"):
            parts = snapshot_ref.split(":")
            if len(parts) == 3:
                _, branch_name, _ = parts
                if self._is_git_repo(workspace_path):
                    try:
                        # Checkout single file from checkpoint branch
                        self._run_git(workspace_path, ["checkout", branch_name, "--", relative_file])
                        logger.info(f"Surgically reverted {relative_file} from git branch {branch_name}")
                        return True
                    except Exception as e:
                        # If checkout fails (e.g. file did not exist in branch), remove it
                        if target_file.exists():
                            target_file.unlink()
                            logger.info(f"Removed {relative_file} because it did not exist in git branch snapshot")
                            return True
                        logger.error(f"Failed to revert file via Git: {e}")
                        return False
            return False

        elif snapshot_ref.startswith("zip:"):
            zip_path_str = snapshot_ref[4:]
            zip_path = Path(zip_path_str)
            if not zip_path.exists():
                raise FileNotFoundError(f"Snapshot zip not found at: {zip_path_str}")

            with zipfile.ZipFile(zip_path, "r") as zipf:
                try:
                    # Check if file exists inside zip
                    info = zipf.getinfo(relative_file)
                    zipf.extract(info, path=str(workspace_path))
                    logger.info(f"Surgically extracted {relative_file} from zip archive")
                    return True
                except KeyError:
                    # File was not in zip (meaning it was created after the snapshot) -> Revert means delete
                    if target_file.exists():
                        if target_file.is_dir():
                            shutil.rmtree(target_file)
                        else:
                            target_file.unlink()
                        logger.info(f"Deleted {relative_file} as it did not exist in zip snapshot")
                        return True
                except Exception as e:
                    logger.error(f"Failed to revert file via Zip: {e}")
                    return False
        return False
