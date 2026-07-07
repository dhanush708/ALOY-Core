"""
memory/tags.py
--------------
TagManager: structured, queryable tag labels on individual memories.
Tags are stored in the `memory_tags` table (see migration 009).
"""
import logging
from datetime import datetime, timezone
from typing import List, Optional

logger = logging.getLogger(__name__)


class TagManager:
    """Add, remove and filter tags associated with memories."""

    def __init__(self, db_pool):
        self.db_pool = db_pool

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _normalise(tags: List[str]) -> List[str]:
        return [t.strip().lower() for t in tags if t.strip()]

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    def add_tags(self, memory_id: str, tags: List[str]) -> None:
        """Idempotently attach one or more tags to a memory."""
        tags = self._normalise(tags)
        if not tags:
            return
        now = self._now()
        rows = [(memory_id, tag, now) for tag in tags]
        with self.db_pool.get_write_connection() as conn:
            conn.executemany(
                "INSERT OR IGNORE INTO memory_tags (memory_id, tag, created_at) VALUES (?, ?, ?)",
                rows,
            )

    def remove_tags(self, memory_id: str, tags: List[str]) -> None:
        """Remove specific tags from a memory."""
        tags = self._normalise(tags)
        if not tags:
            return
        placeholders = ",".join("?" * len(tags))
        with self.db_pool.get_write_connection() as conn:
            conn.execute(
                f"DELETE FROM memory_tags WHERE memory_id = ? AND tag IN ({placeholders})",
                [memory_id] + tags,
            )

    def clear_tags(self, memory_id: str) -> None:
        """Remove all tags from a memory."""
        with self.db_pool.get_write_connection() as conn:
            conn.execute("DELETE FROM memory_tags WHERE memory_id = ?", (memory_id,))

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    def get_tags(self, memory_id: str) -> List[str]:
        """Return all tags for a given memory, sorted alphabetically."""
        with self.db_pool.get_read_connection() as conn:
            cursor = conn.execute(
                "SELECT tag FROM memory_tags WHERE memory_id = ? ORDER BY tag",
                (memory_id,),
            )
            return [row["tag"] for row in cursor.fetchall()]

    def find_by_tags(
        self,
        tags: List[str],
        require_all: bool = False,
        limit: int = 200,
    ) -> List[str]:
        """
        Return memory IDs matching the given tag set.

        Args:
            tags:        List of tags to match.
            require_all: If True, only return memories that have ALL tags
                         (AND semantics). If False, ANY tag suffices (OR).
            limit:       Maximum number of memory IDs to return.
        """
        tags = self._normalise(tags)
        if not tags:
            return []

        placeholders = ",".join("?" * len(tags))

        with self.db_pool.get_read_connection() as conn:
            if require_all:
                cursor = conn.execute(
                    f"""
                    SELECT memory_id
                    FROM   memory_tags
                    WHERE  tag IN ({placeholders})
                    GROUP  BY memory_id
                    HAVING COUNT(DISTINCT tag) = ?
                    LIMIT  ?
                    """,
                    tags + [len(tags), limit],
                )
            else:
                cursor = conn.execute(
                    f"""
                    SELECT DISTINCT memory_id
                    FROM   memory_tags
                    WHERE  tag IN ({placeholders})
                    LIMIT  ?
                    """,
                    tags + [limit],
                )
            return [row["memory_id"] for row in cursor.fetchall()]

    def get_tag_counts(self, limit: int = 50) -> List[dict]:
        """Return the most frequently used tags with their counts."""
        with self.db_pool.get_read_connection() as conn:
            cursor = conn.execute(
                """
                SELECT tag, COUNT(*) as count
                FROM   memory_tags
                GROUP  BY tag
                ORDER  BY count DESC
                LIMIT  ?
                """,
                (limit,),
            )
            return [{"tag": row["tag"], "count": row["count"]} for row in cursor.fetchall()]

    def get_tag_overlap(self, memory_id_a: str, memory_id_b: str) -> float:
        """
        Compute Jaccard similarity between the tag sets of two memories.
        Returns a float in [0, 1].
        """
        tags_a = set(self.get_tags(memory_id_a))
        tags_b = set(self.get_tags(memory_id_b))
        if not tags_a and not tags_b:
            return 0.0
        intersection = len(tags_a & tags_b)
        union = len(tags_a | tags_b)
        return intersection / union if union > 0 else 0.0
