"""
memory/compression.py
---------------------
MemoryCompressor: compresses low-importance memories instead of deleting them.

Strategy:
  - The original full content is snapshotted into `memory_versions` first.
  - The `content` field is replaced with a shorter compressed summary.
  - `metadata["compressed"]` is set to True.
  - The memory remains searchable via FTS5 and vector (re-embedded from summary).
  - `decompress()` restores the original content from the latest version snapshot.
"""
import logging
from datetime import datetime, timezone
from typing import Callable, Awaitable, Optional
import uuid

logger = logging.getLogger(__name__)

# Default heuristic compressor: keep first 200 chars + ellipsis
def _default_summarize(content: str) -> str:
    content = content.strip()
    if len(content) <= 200:
        return content
    # Take first two sentences or first 200 chars
    sentences = content.split(". ")
    if len(sentences) >= 2:
        result = ". ".join(sentences[:2]) + "."
        if len(result) < len(content):
            return result
    return content[:200].rstrip() + "…"


class MemoryCompressor:
    """
    Compresses memory content to save storage and reduce retrieval noise.

    Compression is non-destructive: the original is versioned before any change.
    """

    def __init__(self, db_pool):
        self.db_pool = db_pool

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _snapshot_to_versions(
        self, conn, memory_id: str, content: str, importance: float, confidence: float
    ) -> None:
        """Save current content into memory_versions before modifying."""
        now = datetime.now(timezone.utc).isoformat()
        # Get current version number
        cursor = conn.execute(
            "SELECT version FROM memories WHERE id = ?", (memory_id,)
        )
        row = cursor.fetchone()
        version = row["version"] if row else 1

        conn.execute(
            """
            INSERT OR IGNORE INTO memory_versions
                (id, memory_id, version, content, confidence, importance, changed_by, changed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                memory_id,
                version,
                content,
                confidence,
                importance,
                "compressor",
                now,
            ),
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def compress(
        self,
        memory_id: str,
        summarizer: Optional[Callable[[str], str]] = None,
    ) -> bool:
        """
        Compress a memory's content.

        Args:
            memory_id:  ID of the memory to compress.
            summarizer: Optional callable ``(content: str) -> str`` that returns
                        the compressed version. Defaults to heuristic truncation.

        Returns:
            True if compression was applied, False if already compressed or not found.
        """
        summarize = summarizer or _default_summarize

        with self.db_pool.get_read_connection() as conn:
            cursor = conn.execute(
                "SELECT id, content, importance, confidence, metadata FROM memories WHERE id = ?",
                (memory_id,),
            )
            row = cursor.fetchone()

        if not row:
            logger.warning(f"compress(): memory {memory_id} not found.")
            return False

        import json as _json
        metadata = {}
        try:
            metadata = _json.loads(row["metadata"]) if row["metadata"] else {}
        except Exception:
            pass

        if metadata.get("compressed"):
            logger.debug(f"compress(): memory {memory_id} is already compressed.")
            return False

        original_content = row["content"]
        compressed_content = summarize(original_content)

        if compressed_content == original_content:
            # Nothing to compress
            return False

        metadata["compressed"] = True
        metadata["original_length"] = len(original_content)
        now = datetime.now(timezone.utc).isoformat()

        with self.db_pool.get_write_connection() as conn:
            # Snapshot original first
            self._snapshot_to_versions(
                conn, memory_id, original_content, row["importance"], row["confidence"]
            )
            # Replace content with compressed version
            conn.execute(
                """
                UPDATE memories
                SET content    = ?,
                    metadata   = ?,
                    updated_at = ?,
                    version    = version + 1
                WHERE id = ?
                """,
                (_json.dumps(compressed_content), _json.dumps(metadata), now, memory_id),
            )

        logger.info(
            f"compress(): memory {memory_id} compressed "
            f"{len(original_content)} → {len(compressed_content)} chars."
        )
        return True

    async def decompress(self, memory_id: str) -> bool:
        """
        Restore a compressed memory to its original content.

        Reads the most recent entry in `memory_versions` that predates
        the compression and restores it.

        Returns:
            True on success, False if not compressed or version not found.
        """
        with self.db_pool.get_read_connection() as conn:
            # Get the highest version number snapshot (the pre-compression one)
            cursor = conn.execute(
                """
                SELECT content, version FROM memory_versions
                WHERE  memory_id = ?
                ORDER  BY version DESC
                LIMIT  1
                """,
                (memory_id,),
            )
            ver_row = cursor.fetchone()

            if not ver_row:
                logger.warning(f"decompress(): no version snapshot for {memory_id}.")
                return False

            # Check memory is actually compressed
            cursor2 = conn.execute(
                "SELECT metadata FROM memories WHERE id = ?", (memory_id,)
            )
            mem_row = cursor2.fetchone()

        if not mem_row:
            return False

        import json as _json
        metadata = {}
        try:
            metadata = _json.loads(mem_row["metadata"]) if mem_row["metadata"] else {}
        except Exception:
            pass

        if not metadata.get("compressed"):
            return False

        metadata.pop("compressed", None)
        metadata.pop("original_length", None)
        now = datetime.now(timezone.utc).isoformat()

        with self.db_pool.get_write_connection() as conn:
            conn.execute(
                """
                UPDATE memories
                SET content    = ?,
                    metadata   = ?,
                    updated_at = ?,
                    version    = version + 1
                WHERE id = ?
                """,
                (ver_row["content"], _json.dumps(metadata), now, memory_id),
            )

        logger.info(f"decompress(): memory {memory_id} restored from version {ver_row['version']}.")
        return True

    async def compress_batch(
        self,
        memory_ids: list,
        summarizer: Optional[Callable[[str], str]] = None,
    ) -> int:
        """Compress a list of memories. Returns the count successfully compressed."""
        count = 0
        for mid in memory_ids:
            if await self.compress(mid, summarizer):
                count += 1
        return count
