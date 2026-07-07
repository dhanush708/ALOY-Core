import logging
import math
import struct
from typing import List, Optional
from datetime import datetime, timezone
import json

from .types import Memory
from .store import MemoryStore

logger = logging.getLogger(__name__)

class MemoryLinker:
    """Manages graph relationships between memories."""
    
    def __init__(self, db_pool, store: MemoryStore):
        self.db_pool = db_pool
        self.store = store
        
    async def link(
        self, 
        source_id: str, 
        target_id: str, 
        link_type: str, 
        weight: float = 1.0,
        metadata: dict = None
    ) -> None:
        """Create a directed link between two memories."""
        now = datetime.now(timezone.utc).isoformat()
        meta_json = json.dumps(metadata) if metadata else "{}"
        
        with self.db_pool.get_write_connection() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO memory_links 
                (source_id, target_id, link_type, weight, metadata, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (source_id, target_id, link_type, weight, meta_json, now))
            
    async def get_linked(self, memory_id: str, link_type: str = None) -> List[Memory]:
        """Get all memories linked FROM this memory."""
        sql = """
            SELECT target_id FROM memory_links WHERE source_id = ?
        """
        params = [memory_id]
        
        if link_type:
            sql += " AND link_type = ?"
            params.append(link_type)
            
        sql += " ORDER BY weight DESC"
        
        with self.db_pool.get_read_connection() as conn:
            cursor = conn.execute(sql, tuple(params))
            rows = cursor.fetchall()
            
        results = []
        for row in rows:
            mem = await self.store.get(row["target_id"])
            if mem:
                results.append(mem)
                
        return results

    async def get_neighbors(
        self,
        memory_id: str,
        max_hops: int = 2,
        link_type: Optional[str] = None,
        max_results: int = 20,
    ) -> List[Memory]:
        """
        BFS traversal of the memory link graph up to *max_hops* levels deep.

        Returns a deduplicated, ordered list of neighbour Memory objects.
        The starting memory itself is excluded from the results.
        """
        visited: set = {memory_id}
        frontier: List[str] = [memory_id]
        results: List[Memory] = []

        for _hop in range(max_hops):
            if not frontier:
                break
            next_frontier: List[str] = []
            for fid in frontier:
                neighbours = await self.get_linked(fid, link_type)
                for mem in neighbours:
                    if mem.id not in visited:
                        visited.add(mem.id)
                        next_frontier.append(mem.id)
                        results.append(mem)
                        if len(results) >= max_results:
                            return results
            frontier = next_frontier

        return results

    async def auto_link(
        self,
        memory_id: str,
        candidate_ids: List[str],
        threshold: float = 0.75,
        link_type: str = "semantic",
    ) -> int:
        """
        Automatically create weighted semantic links between *memory_id* and
        any candidate memory whose embedding cosine-similarity exceeds *threshold*.

        Returns the count of new links created.
        """
        # Load anchor embedding
        anchor_emb = self._load_embedding(memory_id)
        if not anchor_emb:
            return 0

        created = 0
        for cid in candidate_ids:
            if cid == memory_id:
                continue
            cand_emb = self._load_embedding(cid)
            if not cand_emb:
                continue
            sim = self._cosine(anchor_emb, cand_emb)
            if sim >= threshold:
                await self.link(
                    source_id=memory_id,
                    target_id=cid,
                    link_type=link_type,
                    weight=round(sim, 4),
                    metadata={"auto": True},
                )
                created += 1

        return created

    # ------------------------------------------------------------------
    # Private vector helpers
    # ------------------------------------------------------------------

    def _load_embedding(self, memory_id: str) -> List[float]:
        """Load the stored embedding for a memory by its ID."""
        with self.db_pool.get_read_connection() as conn:
            cursor = conn.execute(
                """
                SELECT me.embedding
                FROM   memories m
                JOIN   memory_embeddings me ON me.rowid = m.rowid
                WHERE  m.id = ?
                """,
                (memory_id,),
            )
            row = cursor.fetchone()
        if row and row["embedding"]:
            n = len(row["embedding"]) // 4
            return list(struct.unpack(f"{n}f", row["embedding"]))
        return []

    @staticmethod
    def _cosine(a: List[float], b: List[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        na  = math.sqrt(sum(x * x for x in a))
        nb  = math.sqrt(sum(x * x for x in b))
        if na == 0 or nb == 0:
            return 0.0
        return dot / (na * nb)
