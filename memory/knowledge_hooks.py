"""
memory/knowledge_hooks.py
--------------------------
KnowledgeMemoryBridge: extension point for the future Knowledge & Research Engine
(Mission 16).

Provides a clean, forward-compatible interface for:
  - Storing temporary fetched knowledge with a TTL
  - Promoting validated knowledge to long-term permanent storage
  - Retrieving only non-expired temporary knowledge
  - Cleaning up expired temporary entries

Canonical tags:
  knowledge:temp      — temporary, will expire
  knowledge:verified  — promoted to long-term, trusted
  knowledge:source    — web-fetched or external source
"""
import logging
from datetime import datetime, timezone, timedelta
from typing import List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .types import ScoredMemory

logger = logging.getLogger(__name__)

TAG_TEMP     = "knowledge:temp"
TAG_VERIFIED = "knowledge:verified"
TAG_SOURCE   = "knowledge:source"


class KnowledgeMemoryBridge:
    """
    Drop-in interface for the Knowledge & Research Engine (Mission 16).

    All methods are designed to be called by the Knowledge Engine without
    requiring any schema changes — everything works through existing Memory
    fields: `tier`, `expires_at`, `is_protected`, and tags.
    """

    def __init__(self, memory_manager, tag_manager):
        self._mem  = memory_manager
        self._tags = tag_manager

    # ------------------------------------------------------------------
    # Temporary knowledge cache
    # ------------------------------------------------------------------

    async def store_temporary(
        self,
        content: str,
        source_url: Optional[str] = None,
        ttl_hours: float = 24.0,
        confidence: float = 0.6,
        extra_tags: Optional[List[str]] = None,
    ) -> str:
        """
        Store externally fetched knowledge in a temporary short-term cache.

        The memory will be tagged ``knowledge:temp`` and given an ``expires_at``
        timestamp. The consolidation engine will archive it when TTL is exceeded.

        Args:
            content:    The fetched knowledge text.
            source_url: The originating URL or source identifier.
            ttl_hours:  How many hours until expiry (default 24).
            confidence: Source confidence level.
            extra_tags: Additional tags to apply.

        Returns:
            The new memory ID.
        """
        expiry = (datetime.now(timezone.utc) + timedelta(hours=ttl_hours)).isoformat()
        source = source_url or "unknown"

        meta = {"source_url": source, "ttl_hours": ttl_hours}

        mem = await self._mem.store(
            type="knowledge",
            content=content,
            tier="short_term",
            confidence=confidence,
            importance=0.55,
            source=source,
            expires_at=expiry,
            metadata=meta,
        )

        tags = [TAG_TEMP, TAG_SOURCE] + (extra_tags or [])
        if source_url:
            # Tag by domain for easy filtering
            try:
                from urllib.parse import urlparse
                domain = urlparse(source_url).netloc
                if domain:
                    tags.append(f"source:{domain}")
            except Exception:
                pass
        self._tags.add_tags(mem.id, tags)

        logger.info(f"KnowledgeMemoryBridge: stored temp knowledge {mem.id} (ttl={ttl_hours}h)")
        return mem.id

    async def promote_to_permanent(
        self,
        memory_id: str,
        confidence_boost: float = 0.2,
    ) -> bool:
        """
        Promote a temporary knowledge memory to long-term verified storage.

        - Sets tier to 'long_term', clears expires_at
        - Boosts confidence by confidence_boost
        - Replaces 'knowledge:temp' tag with 'knowledge:verified'

        Returns:
            True if the memory was found and promoted, False otherwise.
        """
        mem = await self._mem.get(memory_id)
        if not mem:
            logger.warning(f"promote_to_permanent: memory {memory_id} not found.")
            return False

        new_confidence = min(1.0, mem.confidence + confidence_boost)
        await self._mem.update(
            memory_id,
            tier="long_term",
            expires_at=None,
            confidence=new_confidence,
            importance=max(mem.importance, 0.70),
        )

        # Re-tag
        self._tags.remove_tags(memory_id, [TAG_TEMP])
        self._tags.add_tags(memory_id, [TAG_VERIFIED])

        logger.info(f"KnowledgeMemoryBridge: promoted {memory_id} to long_term verified.")
        return True

    async def get_temporary(
        self,
        query: str,
        limit: int = 10,
    ) -> List["ScoredMemory"]:
        """
        Retrieve non-expired temporary knowledge memories matching the query.

        Only returns memories tagged ``knowledge:temp`` that have not yet expired.
        """
        # Find all memory IDs tagged as temp
        temp_ids = self._tags.find_by_tags([TAG_TEMP], require_all=True, limit=500)
        if not temp_ids:
            return []

        # Filter by expiry in SQL
        now = datetime.now(timezone.utc).isoformat()
        placeholders = ",".join("?" * len(temp_ids))

        with self._mem.db_pool.get_read_connection() as conn:
            cursor = conn.execute(
                f"""
                SELECT id FROM memories
                WHERE  id IN ({placeholders})
                  AND  (expires_at IS NULL OR expires_at > ?)
                  AND  archived_at IS NULL
                """,
                temp_ids + [now],
            )
            valid_ids = [row["id"] for row in cursor.fetchall()]

        if not valid_ids:
            return []

        # Perform a retrieval scoped to these IDs
        results = await self._mem.retrieval.retrieve(query=query, limit=limit)
        return [r for r in results if r.memory.id in set(valid_ids)]

    async def cleanup_expired(self) -> int:
        """
        Archive all temporary knowledge memories that have passed their TTL.
        Returns the count of archived memories.
        """
        now = datetime.now(timezone.utc).isoformat()
        temp_ids = self._tags.find_by_tags([TAG_TEMP], require_all=True, limit=1000)
        if not temp_ids:
            return 0

        placeholders = ",".join("?" * len(temp_ids))
        with self._mem.db_pool.get_write_connection() as conn:
            cursor = conn.execute(
                f"""
                UPDATE memories
                SET    archived_at = ?
                WHERE  id IN ({placeholders})
                  AND  expires_at IS NOT NULL
                  AND  expires_at <= ?
                  AND  archived_at IS NULL
                """,
                [now] + temp_ids + [now],
            )
            count = cursor.rowcount

        if count:
            logger.info(f"KnowledgeMemoryBridge: archived {count} expired temp memories.")
        return count

    # ------------------------------------------------------------------
    # Extension: promotion pipeline batch
    # ------------------------------------------------------------------

    async def batch_promote(self, memory_ids: List[str]) -> int:
        """
        Promote a list of memory IDs to permanent verified storage.
        Returns count of successfully promoted memories.
        """
        count = 0
        for mid in memory_ids:
            if await self.promote_to_permanent(mid):
                count += 1
        return count
