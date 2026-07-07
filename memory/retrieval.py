import logging
from typing import List, Optional, Dict
from datetime import datetime, timezone
import math

from .types import Memory, ScoredMemory
from .store import MemoryStore
from .vector_store import VectorStore
from .embeddings import EmbeddingEngine

logger = logging.getLogger(__name__)

class RetrievalEngine:
    """Hybrid search: FTS5 + Vector + Importance + Recency."""
    
    def __init__(self, db_pool, store: MemoryStore):
        self.db_pool = db_pool
        self.store = store
        self.vector_store = VectorStore(db_pool)
        self.embeddings = EmbeddingEngine()
        
    def _recency_score(self, memory_time_str: str) -> float:
        try:
            m_time = datetime.fromisoformat(memory_time_str)
            now = datetime.now(timezone.utc)
            hours = max(0, (now - m_time).total_seconds() / 3600.0)
            return math.exp(-0.02 * hours)
        except Exception:
            return 0.0
            
    async def retrieve(
        self, 
        query: str, 
        types: Optional[List[str]] = None, 
        limit: int = 10,
        archived: bool = False,
        tags: Optional[List[str]] = None,
    ) -> List[ScoredMemory]:
        """Hybrid search combining FTS5 and vector similarity via Reciprocal Rank Fusion.
        
        Args:
            query:    The search text.
            types:    Optional list of memory types to restrict to.
            limit:    Maximum number of results.
            archived: Whether to include archived memories.
            tags:     Optional list of tags; when provided, only memories that
                      have at least one of these tags are returned.
        """
        if not query.strip():
            return []

        # Pre-filter by tags if requested
        tag_allowed_ids: Optional[set] = None
        if tags:
            from .tags import TagManager
            _tm = TagManager(self.db_pool)
            tag_ids = _tm.find_by_tags(tags, require_all=False, limit=2000)
            tag_allowed_ids = set(tag_ids)
            if not tag_allowed_ids:
                return []  # No memories with those tags → empty result
            
        # 1. Generate query embedding
        query_embedding = await self.embeddings.generate(query)
        
        # Sanitize query for FTS5 (remove special FTS chars, or wrap in quotes if we want literal)
        import re
        fts_query = re.sub(r'[^a-zA-Z0-9\s]', ' ', query).strip()
        if not fts_query:
            # Fallback if query was entirely special chars, FTS will fail or return nothing, so just match everything or skip FTS.
            # We'll just set it to something safe or skip FTS. Since vector search will still work, we can just pass a dummy query or skip FTS rows.
            fts_query = "dummy_safe_query_never_match"
            
        with self.db_pool.get_read_connection() as conn:
            # 2. FTS5 Search
            sql_fts = """
                SELECT m.rowid, m.id, m.importance, m.created_at, m.last_accessed_at, fts.rank
                FROM memories_fts fts
                JOIN memories m ON fts.rowid = m.rowid
                WHERE memories_fts MATCH ?
            """
            params_fts = [fts_query]
            if types:
                sql_fts += f" AND m.type IN ({','.join(['?'] * len(types))})"
                params_fts.extend(types)
            if not archived:
                sql_fts += " AND m.archived_at IS NULL"
            sql_fts += " ORDER BY fts.rank LIMIT 50"
            
            cursor = conn.execute(sql_fts, tuple(params_fts))
            fts_rows = cursor.fetchall()
            
            # 3. Vector Search
            vec_results = []
            if query_embedding:
                # Get more vector results to ensure overlap
                vec_results = await self.vector_store.search(query_embedding, limit=50)
                
            # Filter vector results by types/archived (by querying memories table)
            filtered_vec_rows = []
            if vec_results:
                rowids = [r[0] for r in vec_results]
                placeholders = ",".join(["?"] * len(rowids))
                sql_vec_filter = f"""
                    SELECT rowid, id, importance, created_at, last_accessed_at 
                    FROM memories WHERE rowid IN ({placeholders})
                """
                params_vec = list(rowids)
                if types:
                    sql_vec_filter += f" AND type IN ({','.join(['?'] * len(types))})"
                    params_vec.extend(types)
                if not archived:
                    sql_vec_filter += " AND archived_at IS NULL"
                    
                cursor = conn.execute(sql_vec_filter, tuple(params_vec))
                valid_memories = {row["rowid"]: row for row in cursor.fetchall()}
                
                for rowid, dist in vec_results:
                    if rowid in valid_memories:
                        filtered_vec_rows.append((rowid, dist, valid_memories[rowid]))
                        
            # 4. Reciprocal Rank Fusion (RRF)
            # RRF Score = 1 / (k + rank)
            k = 60
            scores: Dict[int, float] = {}
            row_data: Dict[int, dict] = {}
            
            # Add FTS scores
            for rank_idx, row in enumerate(fts_rows):
                rowid = row["rowid"]
                scores[rowid] = scores.get(rowid, 0.0) + (1.0 / (k + rank_idx + 1))
                row_data[rowid] = row
                
            # Add Vector scores
            for rank_idx, (rowid, dist, row) in enumerate(filtered_vec_rows):
                scores[rowid] = scores.get(rowid, 0.0) + (1.0 / (k + rank_idx + 1))
                row_data[rowid] = row
                
            if not scores:
                return []

            # Apply tag filter post-RRF (tag_allowed_ids are memory IDs from tags table)
            if tag_allowed_ids:
                # We need to map rowid → memory id to check against allowed set
                filtered_scores: Dict[int, float] = {}
                for rowid, score_val in scores.items():
                    mem_id = row_data[rowid]["id"]
                    if mem_id and mem_id in tag_allowed_ids:
                        filtered_scores[rowid] = score_val
                scores = filtered_scores
                if not scores:
                    return []
                
            # 5. Normalize RRF scores and apply Importance/Recency boosts
            max_rrf = max(scores.values())
            scored_candidates = []
            
            for rowid, rrf in scores.items():
                normalized_rrf = rrf / max_rrf if max_rrf > 0 else 0
                row = row_data[rowid]
                
                importance = row["importance"]
                recency = self._recency_score(row["last_accessed_at"] or row["created_at"])
                
                # Final hybrid score: 50% semantics/text, 25% importance, 25% recency
                final_score = (0.5 * normalized_rrf) + (0.25 * importance) + (0.25 * recency)
                
                scored_candidates.append({
                    "id": row["id"],
                    "score": final_score,
                    "details": {
                        "rrf": normalized_rrf,
                        "importance": importance,
                        "recency": recency
                    }
                })
                
            # Sort and truncate
            scored_candidates.sort(key=lambda x: x["score"], reverse=True)
            top_candidates = scored_candidates[:limit]
            
            # 6. Hydrate
            results = []
            for cand in top_candidates:
                mem = await self.store.get(cand["id"])
                if mem:
                    results.append(ScoredMemory(
                        memory=mem,
                        score=cand["score"],
                        relevance_details=cand["details"]
                    ))
                    
            return results

    async def retrieve_linked(
        self,
        memory_id: str,
        query: str,
        limit: int = 10,
        max_hops: int = 2,
    ) -> List[ScoredMemory]:
        """
        Retrieve memories from the graph-linked neighbourhood of *memory_id*.

        Collects up to *limit* neighbours via BFS (max_hops), then scores each
        against *query* using the same RRF pipeline.

        Returns ScoredMemory objects sorted by relevance.
        """
        from .linking import MemoryLinker
        linker = MemoryLinker(self.db_pool, self.store)
        neighbours = await linker.get_neighbors(memory_id, max_hops=max_hops, max_results=limit * 4)
        if not neighbours:
            return []

        # Score each neighbour by embedding similarity to query
        query_embedding = await self.embeddings.generate(query)
        if not query_embedding:
            # Fall back to returning neighbours unscored
            from .types import ScoredMemory
            return [ScoredMemory(memory=m, score=0.5) for m in neighbours[:limit]]

        from .vector_store import serialize_f32
        from .clustering import _cosine, _deserialize_f32
        import struct

        scored: List[ScoredMemory] = []
        for mem in neighbours:
            # Load embedding for this memory
            with self.db_pool.get_read_connection() as conn:
                cursor = conn.execute(
                    "SELECT me.embedding FROM memories m "
                    "JOIN memory_embeddings me ON me.rowid = m.rowid "
                    "WHERE m.id = ?",
                    (mem.id,),
                )
                row = cursor.fetchone()
            if not row or not row["embedding"]:
                continue
            mem_emb = _deserialize_f32(row["embedding"])
            sim = _cosine(query_embedding, mem_emb)
            scored.append(ScoredMemory(
                memory=mem,
                score=sim,
                relevance_details={"cosine": sim},
            ))

        scored.sort(key=lambda x: x.score, reverse=True)
        return scored[:limit]
