import json
import uuid
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

from database.connection import DatabaseConnectionPool
from project.manifest import ManifestLoader
from project.tree import DirectoryTreeBuilder
from project.discovery import ProjectDiscovery
from project.session import ProjectSession

logger = logging.getLogger(__name__)


class ProjectManager:
    """Manages project registrations, workspaces, directories indexing, and active sessions."""

    def __init__(self, db_pool: DatabaseConnectionPool):
        self.db_pool = db_pool

    def create_project(
        self,
        name: str,
        root_path: str | Path,
        description: str = "",
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Registers a project, auto-initializing .aloy/manifest.yaml if not present."""
        root = Path(root_path).resolve()
        if not root.exists():
            logger.info("Project root path %s does not exist. Creating directory.", root)
            root.mkdir(parents=True, exist_ok=True)
        elif not root.is_dir():
            raise NotADirectoryError(f"Root path is not a directory: {root}")

        root_str = root.as_posix()

        # Check if already registered
        existing = self.get_project_by_root(root_str)
        if existing:
            return existing

        # Ensure manifest is initialized
        manifest_path = ManifestLoader.init_manifest(root, name, description)
        manifest_data = ManifestLoader.load(root)
        project_name = manifest_data["project"]["name"]

        project_id = str(uuid.uuid4())
        created_at = datetime.now(timezone.utc).isoformat()
        
        meta_dict = metadata or {}
        meta_dict["manifest"] = manifest_data["project"]
        meta_str = json.dumps(meta_dict)

        with self.db_pool.get_write_connection() as conn:
            conn.execute(
                """
                INSERT INTO projects (id, name, root_path, manifest_path, created_at, updated_at, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    project_name,
                    root_str,
                    manifest_path.as_posix(),
                    created_at,
                    created_at,
                    meta_str
                )
            )

        return {
            "id": project_id,
            "name": project_name,
            "root_path": root_str,
            "manifest_path": manifest_path.as_posix(),
            "created_at": created_at,
            "updated_at": created_at,
            "metadata": meta_dict
        }

    def get_project(self, project_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves project details by ID."""
        with self.db_pool.get_read_connection() as conn:
            row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
            if not row:
                return None
            return self._row_to_project_dict(row)

    def get_project_by_root(self, root_path: str | Path) -> Optional[Dict[str, Any]]:
        """Retrieves project details by root path."""
        root_str = Path(root_path).resolve().as_posix()
        with self.db_pool.get_read_connection() as conn:
            row = conn.execute("SELECT * FROM projects WHERE root_path = ?", (root_str,)).fetchone()
            if not row:
                return None
            return self._row_to_project_dict(row)

    def list_projects(self) -> List[Dict[str, Any]]:
        """Lists all registered projects."""
        with self.db_pool.get_read_connection() as conn:
            rows = conn.execute("SELECT * FROM projects ORDER BY name").fetchall()
            return [self._row_to_project_dict(row) for row in rows]

    def delete_project(self, project_id: str) -> bool:
        """Deletes a project registration (and all associated files/sessions)."""
        with self.db_pool.get_write_connection() as conn:
            conn.execute("DELETE FROM project_files WHERE project_id = ?", (project_id,))
            conn.execute("DELETE FROM project_sessions WHERE project_id = ?", (project_id,))
            cursor = conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
            return cursor.rowcount > 0

    def start_session(self, project_id: str, metadata: Optional[Dict[str, Any]] = None) -> ProjectSession:
        """Starts a new session, ending any previously active session for the project."""
        # Ensure project exists
        project = self.get_project(project_id)
        if not project:
            raise ValueError(f"Project with ID {project_id} does not exist.")

        # End active session if exists
        active = self.get_active_session(project_id)
        if active:
            self.end_session(active.id, summary="Auto-ended on new session start.")

        session_id = str(uuid.uuid4())
        started_at = datetime.now(timezone.utc).isoformat()
        meta_str = json.dumps(metadata or {})

        with self.db_pool.get_write_connection() as conn:
            conn.execute(
                """
                INSERT INTO project_sessions (id, project_id, started_at, ended_at, summary, metadata)
                VALUES (?, ?, ?, NULL, '', ?)
                """,
                (session_id, project_id, started_at, meta_str)
            )

        return ProjectSession(session_id, project_id, started_at, None, "", metadata)

    def save_session(self, session: ProjectSession) -> None:
        """Saves the current state of a ProjectSession to the database."""
        with self.db_pool.get_write_connection() as conn:
            conn.execute(
                """
                UPDATE project_sessions
                SET ended_at = ?, summary = ?, metadata = ?
                WHERE id = ?
                """,
                (
                    session.ended_at.isoformat() if session.ended_at else None,
                    session.summary,
                    json.dumps(session.metadata),
                    session.id
                )
            )

    def end_session(
        self,
        session_or_id: str | ProjectSession,
        summary: str = "",
        metadata: Optional[Dict[str, Any]] = None
    ) -> Optional[ProjectSession]:
        """Ends the project session and persists it."""
        if isinstance(session_or_id, ProjectSession):
            session = session_or_id
        else:
            with self.db_pool.get_read_connection() as conn:
                row = conn.execute("SELECT * FROM project_sessions WHERE id = ?", (session_or_id,)).fetchone()
                if not row:
                    return None
            session = ProjectSession.from_row(row)

        session.end(summary, metadata)
        self.save_session(session)
        return session

    def get_active_session(self, project_id: str) -> Optional[ProjectSession]:
        """Gets currently active session for a project."""
        with self.db_pool.get_read_connection() as conn:
            row = conn.execute(
                "SELECT * FROM project_sessions WHERE project_id = ? AND ended_at IS NULL",
                (project_id,)
            ).fetchone()
            if not row:
                return None
            return ProjectSession.from_row(row)

    def list_sessions(self, project_id: str) -> List[ProjectSession]:
        """Lists all sessions for a project."""
        with self.db_pool.get_read_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM project_sessions WHERE project_id = ? ORDER BY started_at DESC",
                (project_id,)
            ).fetchall()
            return [ProjectSession.from_row(row) for row in rows]

    def index_project_files(self, project_id: str) -> Dict[str, Any]:
        """Scans project files on disk, updating the project_files index."""
        project = self.get_project(project_id)
        if not project:
            raise ValueError(f"Project with ID {project_id} does not exist.")

        root_path = Path(project["root_path"])
        manifest_data = ManifestLoader.load(root_path)
        exclude_patterns = manifest_data["project"]["exclude_patterns"]

        # Build flat list of file paths from disk
        disk_files = DirectoryTreeBuilder.build_flat(root_path, exclude_patterns)
        disk_rel_paths = {f.relative_to(root_path).as_posix(): f for f in disk_files}

        # Query currently indexed files
        with self.db_pool.get_read_connection() as conn:
            rows = conn.execute("SELECT file_path, metadata FROM project_files WHERE project_id = ?", (project_id,)).fetchall()
            db_files = {row["file_path"]: json.loads(row["metadata"] or "{}") for row in rows}

        added = 0
        updated = 0
        removed = 0
        now = datetime.now(timezone.utc).isoformat()

        # Identify changes
        to_upsert = []
        for rel_path, full_path in disk_rel_paths.items():
            try:
                stat = full_path.stat()
                mtime = stat.st_mtime
                size = stat.st_size
            except OSError:
                mtime = 0.0
                size = 0
            
            file_type = full_path.suffix.lstrip(".") or "unknown"
            
            file_metadata = {
                "size_bytes": size,
                "modified_at": datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()
            }

            if rel_path not in db_files:
                # New file
                added += 1
                to_upsert.append((str(uuid.uuid4()), project_id, rel_path, file_type, now, json.dumps(file_metadata)))
            else:
                # Check if changed (using simple size/mtime check)
                old_meta = db_files[rel_path]
                if old_meta.get("size_bytes") != size or old_meta.get("modified_at") != file_metadata["modified_at"]:
                    updated += 1
                    # Re-use or overwrite ID. Easiest is to generate a new one since we do REPLACE
                    to_upsert.append((str(uuid.uuid4()), project_id, rel_path, file_type, now, json.dumps(file_metadata)))

        # Find deleted files
        to_delete = [p for p in db_files.keys() if p not in disk_rel_paths]
        removed = len(to_delete)

        # Apply changes in DB
        with self.db_pool.get_write_connection() as conn:
            # 1. Upsert files
            if to_upsert:
                conn.executemany(
                    """
                    INSERT OR REPLACE INTO project_files (id, project_id, file_path, file_type, last_indexed_at, metadata)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    to_upsert
                )
            
            # 2. Delete missing files
            if to_delete:
                # Chunk delete just in case of huge list
                for i in range(0, len(to_delete), 500):
                    chunk = to_delete[i:i+500]
                    placeholders = ",".join("?" for _ in chunk)
                    conn.execute(
                        f"DELETE FROM project_files WHERE project_id = ? AND file_path IN ({placeholders})",
                        [project_id] + chunk
                    )

            # 3. Update project modified timestamp
            conn.execute("UPDATE projects SET updated_at = ? WHERE id = ?", (now, project_id))

        total = len(disk_rel_paths)
        return {
            "added": added,
            "updated": updated,
            "removed": removed,
            "total": total
        }

    def _row_to_project_dict(self, row: Any) -> Dict[str, Any]:
        d = dict(row)
        try:
            d["metadata"] = json.loads(d["metadata"] or "{}")
        except ValueError:
            d["metadata"] = {}
        return d
