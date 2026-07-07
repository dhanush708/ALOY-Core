"""
memory/collections.py
---------------------
CollectionManager: workspace / user / project / global scoped memory groups.
Collections are stored in `memory_collections` and `memory_collection_members`
tables (see migration 009).
"""
import json
import logging
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any

logger = logging.getLogger(__name__)

VALID_SCOPES = {"workspace", "user", "project", "global"}


@dataclass
class MemoryCollection:
    id: str
    name: str
    scope: str                        # workspace | user | project | global
    scope_id: Optional[str] = None   # e.g. workspace_id, user_id, project_id
    description: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["metadata"] = json.dumps(d["metadata"])
        return d

    @classmethod
    def from_row(cls, row) -> "MemoryCollection":
        d = dict(row)
        if d.get("metadata"):
            try:
                d["metadata"] = json.loads(d["metadata"])
            except Exception:
                d["metadata"] = {}
        else:
            d["metadata"] = {}
        return cls(**d)


class CollectionManager:
    """CRUD operations for memory collections and their memberships."""

    def __init__(self, db_pool):
        self.db_pool = db_pool

    # ------------------------------------------------------------------
    # Collection CRUD
    # ------------------------------------------------------------------

    def create(
        self,
        name: str,
        scope: str = "global",
        scope_id: Optional[str] = None,
        description: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> MemoryCollection:
        if scope not in VALID_SCOPES:
            raise ValueError(f"scope must be one of {VALID_SCOPES}, got '{scope}'")

        col = MemoryCollection(
            id=str(uuid.uuid4()),
            name=name,
            scope=scope,
            scope_id=scope_id,
            description=description,
            metadata=metadata or {},
        )
        d = col.to_dict()
        columns = ", ".join(d.keys())
        placeholders = ", ".join("?" * len(d))
        with self.db_pool.get_write_connection() as conn:
            conn.execute(
                f"INSERT INTO memory_collections ({columns}) VALUES ({placeholders})",
                tuple(d.values()),
            )
        return col

    def get(self, collection_id: str) -> Optional[MemoryCollection]:
        with self.db_pool.get_read_connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM memory_collections WHERE id = ?", (collection_id,)
            )
            row = cursor.fetchone()
        return MemoryCollection.from_row(row) if row else None

    def list_by_scope(
        self,
        scope: str,
        scope_id: Optional[str] = None,
    ) -> List[MemoryCollection]:
        sql = "SELECT * FROM memory_collections WHERE scope = ?"
        params: list = [scope]
        if scope_id is not None:
            sql += " AND scope_id = ?"
            params.append(scope_id)
        sql += " ORDER BY created_at DESC"
        with self.db_pool.get_read_connection() as conn:
            cursor = conn.execute(sql, params)
            return [MemoryCollection.from_row(r) for r in cursor.fetchall()]

    def delete(self, collection_id: str) -> bool:
        with self.db_pool.get_write_connection() as conn:
            cursor = conn.execute(
                "DELETE FROM memory_collections WHERE id = ?", (collection_id,)
            )
            return cursor.rowcount > 0

    # ------------------------------------------------------------------
    # Membership
    # ------------------------------------------------------------------

    def add_memory(self, collection_id: str, memory_id: str) -> None:
        """Add a memory to a collection (idempotent)."""
        now = datetime.now(timezone.utc).isoformat()
        with self.db_pool.get_write_connection() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO memory_collection_members
                    (collection_id, memory_id, added_at)
                VALUES (?, ?, ?)
                """,
                (collection_id, memory_id, now),
            )

    def remove_memory(self, collection_id: str, memory_id: str) -> None:
        with self.db_pool.get_write_connection() as conn:
            conn.execute(
                "DELETE FROM memory_collection_members WHERE collection_id = ? AND memory_id = ?",
                (collection_id, memory_id),
            )

    def list_memory_ids(self, collection_id: str) -> List[str]:
        """Return all memory IDs that belong to a collection."""
        with self.db_pool.get_read_connection() as conn:
            cursor = conn.execute(
                "SELECT memory_id FROM memory_collection_members WHERE collection_id = ? ORDER BY added_at",
                (collection_id,),
            )
            return [row["memory_id"] for row in cursor.fetchall()]

    def list_collections_for_memory(self, memory_id: str) -> List[MemoryCollection]:
        """Return all collections a given memory belongs to."""
        with self.db_pool.get_read_connection() as conn:
            cursor = conn.execute(
                """
                SELECT c.* FROM memory_collections c
                JOIN   memory_collection_members m ON m.collection_id = c.id
                WHERE  m.memory_id = ?
                """,
                (memory_id,),
            )
            return [MemoryCollection.from_row(r) for r in cursor.fetchall()]

    def find_or_create_workspace_collection(
        self, workspace_id: str, name: str = "default"
    ) -> MemoryCollection:
        """Retrieve the default collection for a workspace, creating it if absent."""
        cols = self.list_by_scope("workspace", scope_id=workspace_id)
        for c in cols:
            if c.name == name:
                return c
        return self.create(
            name=name,
            scope="workspace",
            scope_id=workspace_id,
            description=f"Default collection for workspace {workspace_id}",
        )
