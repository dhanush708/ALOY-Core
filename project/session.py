from datetime import datetime, timezone
import json
from typing import Dict, Any, List, Optional


class ProjectSession:
    """Represents a working session within a project context."""

    def __init__(
        self,
        session_id: str,
        project_id: str,
        started_at: str | datetime,
        ended_at: Optional[str | datetime] = None,
        summary: Optional[str] = None,
        metadata: Optional[Dict[str, Any] | str] = None
    ):
        self.id = session_id
        self.project_id = project_id
        
        if isinstance(started_at, str):
            self.started_at = datetime.fromisoformat(started_at)
        else:
            self.started_at = started_at

        if isinstance(ended_at, str):
            self.ended_at = datetime.fromisoformat(ended_at)
        elif ended_at is not None:
            self.ended_at = ended_at
        else:
            self.ended_at = None
            
        self.summary = summary or ""
        
        if isinstance(metadata, str):
            try:
                self.metadata = json.loads(metadata)
            except ValueError:
                self.metadata = {}
        else:
            self.metadata = metadata or {}

    def end(self, summary: str = "", additional_metadata: Optional[Dict[str, Any]] = None) -> None:
        """Ends the project session and updates metadata."""
        self.ended_at = datetime.now(timezone.utc)
        if summary:
            self.summary = summary
        if additional_metadata:
            self.metadata.update(additional_metadata)

    def log_change(self, file_path: str, change_type: str = "modify") -> None:
        """Logs a file change within the session metadata."""
        if "changes" not in self.metadata:
            self.metadata["changes"] = []
        self.metadata["changes"].append({
            "file_path": file_path,
            "type": change_type,
            "timestamp": datetime.now(timezone.utc).isoformat()
        })

    def log_command(self, command: str, exit_code: int = 0) -> None:
        """Logs a command execution within the session metadata."""
        if "commands" not in self.metadata:
            self.metadata["commands"] = []
        self.metadata["commands"].append({
            "command": command,
            "exit_code": exit_code,
            "timestamp": datetime.now(timezone.utc).isoformat()
        })

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "started_at": self.started_at.isoformat(),
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
            "summary": self.summary,
            "metadata": json.dumps(self.metadata)
        }

    @classmethod
    def from_row(cls, row: Dict[str, Any] | Any) -> "ProjectSession":
        # Supports sqlite3.Row or dict
        d = dict(row)
        return cls(
            session_id=d["id"],
            project_id=d["project_id"],
            started_at=d["started_at"],
            ended_at=d["ended_at"],
            summary=d["summary"],
            metadata=d["metadata"]
        )
