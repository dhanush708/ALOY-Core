import os
import shutil
import zipfile
import logging
import subprocess
import fnmatch
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)


class WorkspaceSnapshotManager:
    """
    Captures project workspace state before execution.
    Supports git-based branches (if git repository is present) and zip-based archives.
    """

    def __init__(self, snapshots_dir: Optional[Path] = None):
        # Default to a sub-folder in workspace or temp dir
        self.snapshots_dir = snapshots_dir

    def _get_snapshots_dir(self, workspace_path: Path) -> Path:
        if self.snapshots_dir:
            self.snapshots_dir.mkdir(parents=True, exist_ok=True)
            return self.snapshots_dir
        path = workspace_path / ".aloy" / "snapshots"
        path.mkdir(parents=True, exist_ok=True)
        return path

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

    async def create_snapshot(self, workspace_path: str, session_id: str) -> str:
        """
        Creates a snapshot of the workspace.
        Returns a string reference to the snapshot (e.g. 'git:branch_name:orig_branch' or 'zip:path').
        """
        workspace = Path(workspace_path).resolve()
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")

        # Try Git first
        if self._is_git_repo(workspace):
            try:
                # Get current branch/commit
                orig_branch = ""
                try:
                    orig_branch = self._run_git(workspace, ["branch", "--show-current"])
                except Exception:
                    pass
                if not orig_branch:
                    # If detached HEAD, get current commit hash
                    orig_branch = self._run_git(workspace, ["rev-parse", "HEAD"])

                branch_name = f"aloy-snap-{session_id[:8]}-{timestamp}"
                
                # Check status
                status = self._run_git(workspace, ["status", "--porcelain"])
                
                # Create branch and commit
                self._run_git(workspace, ["checkout", "-b", branch_name])
                
                if status:
                    self._run_git(workspace, ["add", "-A"])
                    self._run_git(workspace, ["commit", "-m", f"ALOY Auto-snapshot {timestamp}", "--no-verify"])
                else:
                    # Commit an empty change so the branch exists and is distinct
                    self._run_git(workspace, ["commit", "--allow-empty", "-m", f"ALOY Auto-snapshot empty {timestamp}", "--no-verify"])

                # Switch back to original branch
                self._run_git(workspace, ["checkout", orig_branch])

                ref = f"git:{branch_name}:{orig_branch}"
                logger.info("Created git-based snapshot: %s", ref)
                return ref
            except Exception as e:
                logger.warning("Git snapshot failed, falling back to zip: %s", e)

        # Fallback to Zip
        snap_dir = self._get_snapshots_dir(workspace)
        zip_path = snap_dir / f"snap_{session_id[:8]}_{timestamp}.zip"
        
        # Read manifest exclude patterns if possible
        exclude_patterns = [".git", "__pycache__", ".aloy", "node_modules", "venv", ".venv"]
        manifest_yaml = workspace / ".aloy" / "manifest.yaml"
        if manifest_yaml.exists():
            try:
                import yaml
                with open(manifest_yaml, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
                    excludes = data.get("project", {}).get("exclude_patterns", [])
                    if excludes:
                        exclude_patterns = excludes
            except Exception:
                pass

        def should_exclude(p: Path) -> bool:
            rel = p.relative_to(workspace).as_posix()
            for pattern in exclude_patterns:
                if fnmatch.fnmatch(rel, pattern) or any(fnmatch.fnmatch(part, pattern) for part in p.relative_to(workspace).parts):
                    return True
            return False

        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
            for root, dirs, files in os.walk(workspace):
                root_path = Path(root)
                # Modify dirs in-place to prune excluded directories from os.walk
                for d in list(dirs):
                    if should_exclude(root_path / d):
                        dirs.remove(d)
                for f in files:
                    file_path = root_path / f
                    if not should_exclude(file_path):
                        arcname = file_path.relative_to(workspace).as_posix()
                        zipf.write(file_path, arcname)

        ref = f"zip:{zip_path.resolve().as_posix()}"
        logger.info("Created zip-based snapshot: %s", ref)
        return ref

    async def restore_snapshot(self, workspace_path: str, snapshot_ref: str) -> None:
        """Restores the workspace to the state described by snapshot_ref."""
        workspace = Path(workspace_path).resolve()

        if snapshot_ref.startswith("git:"):
            parts = snapshot_ref.split(":")
            if len(parts) == 3:
                _, branch_name, orig_branch = parts
                if self._is_git_repo(workspace):
                    # Hard reset to the snapshot branch state on the original branch
                    self._run_git(workspace, ["checkout", orig_branch])
                    self._run_git(workspace, ["reset", "--hard", branch_name])
                    # Clean untracked files
                    self._run_git(workspace, ["clean", "-fdx", "-e", ".aloy/"])
                    logger.info("Restored git-based snapshot %s", branch_name)
                    return
            raise ValueError(f"Invalid git snapshot ref or not a git repository: {snapshot_ref}")

        elif snapshot_ref.startswith("zip:"):
            zip_path_str = snapshot_ref[4:]
            zip_path = Path(zip_path_str)
            if not zip_path.exists():
                raise FileNotFoundError(f"Snapshot zip not found: {zip_path_str}")

            # Clear all files in workspace except .aloy
            for item in workspace.iterdir():
                if item.name == ".aloy":
                    continue
                if item.is_dir():
                    shutil.rmtree(item)
                else:
                    item.unlink()

            # Extract zip
            with zipfile.ZipFile(zip_path, "r") as zipf:
                zipf.extractall(workspace)

            logger.info("Restored zip-based snapshot: %s", zip_path_str)
            return

        raise ValueError(f"Unsupported snapshot ref format: {snapshot_ref}")

    async def list_snapshots(self, workspace_path: str) -> List[Dict[str, Any]]:
        """List zip snapshots in .aloy/snapshots directory."""
        workspace = Path(workspace_path).resolve()
        snap_dir = self._get_snapshots_dir(workspace)
        
        snapshots = []
        for item in snap_dir.glob("*.zip"):
            stat = item.stat()
            snapshots.append({
                "name": item.name,
                "path": item.resolve().as_posix(),
                "created_at": datetime.utcfromtimestamp(stat.st_mtime).isoformat(),
                "size_bytes": stat.st_size,
            })
        return sorted(snapshots, key=lambda x: x["created_at"], reverse=True)

    async def delete_snapshot(self, workspace_path: str, snapshot_ref: str) -> None:
        """Deletes a snapshot file or branch."""
        workspace = Path(workspace_path).resolve()

        if snapshot_ref.startswith("git:"):
            parts = snapshot_ref.split(":")
            if len(parts) == 3:
                _, branch_name, _ = parts
                if self._is_git_repo(workspace):
                    try:
                        self._run_git(workspace, ["branch", "-D", branch_name])
                    except Exception:
                        pass
                    return

        elif snapshot_ref.startswith("zip:"):
            zip_path_str = snapshot_ref[4:]
            zip_path = Path(zip_path_str)
            if zip_path.exists():
                zip_path.unlink()
            return
