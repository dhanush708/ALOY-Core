import logging
from typing import List, Tuple
import struct

logger = logging.getLogger(__name__)

def serialize_f32(vector: List[float]) -> bytes:
    """Serializes a list of floats into a contiguous byte array of 32-bit floats."""
    return struct.pack('%sf' % len(vector), *vector)

class VectorStore:
    """Manages sqlite-vec operations."""
    
    def __init__(self, db_pool):
        self.db_pool = db_pool
        
    async def upsert_embedding(self, memory_rowid: int, embedding: List[float]) -> None:
        """Upsert a memory embedding."""
        if not embedding or len(embedding) != 768:
            logger.warning(f"Invalid embedding length {len(embedding) if embedding else 0}. Expected 768.")
            return
            
        vector_bytes = serialize_f32(embedding)
        
        with self.db_pool.get_write_connection() as conn:
            # We tie the vector rowid directly to the memories table rowid
            conn.execute("""
                INSERT OR REPLACE INTO memory_embeddings (rowid, embedding)
                VALUES (?, ?)
            """, (memory_rowid, vector_bytes))
            
    async def delete_embedding(self, memory_rowid: int) -> None:
        """Delete an embedding."""
        with self.db_pool.get_write_connection() as conn:
            conn.execute("DELETE FROM memory_embeddings WHERE rowid = ?", (memory_rowid,))
            
    async def search(self, query_embedding: List[float], limit: int = 50) -> List[Tuple[int, float]]:
        """
        Search for nearest neighbors.
        Returns a list of (memory_rowid, distance).
        Note: sqlite-vec returns Euclidean distance. Lower is closer.
        """
        if not query_embedding or len(query_embedding) != 768:
            return []
            
        vector_bytes = serialize_f32(query_embedding)
        
        with self.db_pool.get_read_connection() as conn:
            cursor = conn.execute("""
                SELECT rowid, distance
                FROM memory_embeddings
                WHERE embedding MATCH ? AND k = ?
                ORDER BY distance
            """, (vector_bytes, limit))
            
            rows = cursor.fetchall()
            return [(row["rowid"], row["distance"]) for row in rows]
