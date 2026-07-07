import logging
from typing import List, Optional, Dict, Any
from .types import Memory

logger = logging.getLogger(__name__)

class MemoryStore:
    """SQLite CRUD operations for the memories table."""
    
    def __init__(self, db_pool):
        self.db_pool = db_pool
        
    async def create(self, memory: Memory) -> None:
        """Insert a new memory."""
        data = memory.to_dict()
        columns = ", ".join(data.keys())
        placeholders = ", ".join(["?"] * len(data))
        values = tuple(data.values())
        
        with self.db_pool.get_write_connection() as conn:
            conn.execute(f"INSERT INTO memories ({columns}) VALUES ({placeholders})", values)
            
    async def get(self, memory_id: str) -> Optional[Memory]:
        """Retrieve a memory by ID."""
        with self.db_pool.get_read_connection() as conn:
            # exclude embedding blob from select to save memory overhead
            cursor = conn.execute("""
                SELECT id, type, tier, category, content, summary, source, source_id,
                       confidence, importance, emotional_weight, access_count, 
                       last_accessed_at, decay_rate, created_at, updated_at, 
                       expires_at, archived_at, version, is_protected, metadata
                FROM memories 
                WHERE id = ?
            """, (memory_id,))
            row = cursor.fetchone()
            if row:
                return Memory.from_row(row)
        return None
        
    async def update(self, memory_id: str, updates: Dict[str, Any]) -> None:
        """Update specific fields of a memory."""
        if not updates:
            return
            
        from .types import utc_now
        updates["updated_at"] = utc_now()
        
        # Increment version implicitly
        set_clause = ", ".join([f"{k} = ?" for k in updates.keys()]) + ", version = version + 1"
        values = tuple(updates.values()) + (memory_id,)
        
        with self.db_pool.get_write_connection() as conn:
            conn.execute(f"UPDATE memories SET {set_clause} WHERE id = ?", values)
            
    async def delete(self, memory_id: str, force: bool = False) -> bool:
        """Delete a memory. If not force, refuses to delete protected memories."""
        with self.db_pool.get_write_connection() as conn:
            if not force:
                cursor = conn.execute("SELECT is_protected FROM memories WHERE id = ?", (memory_id,))
                row = cursor.fetchone()
                if row and row["is_protected"]:
                    logger.warning(f"Attempted to delete protected memory {memory_id} without force.")
                    return False
                    
            cursor = conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
            return cursor.rowcount > 0
            
    async def record_access(self, memory_id: str) -> None:
        """Increment access count and update last_accessed_at."""
        from .types import utc_now
        with self.db_pool.get_write_connection() as conn:
            conn.execute("""
                UPDATE memories 
                SET access_count = access_count + 1,
                    last_accessed_at = ?
                WHERE id = ?
            """, (utc_now(), memory_id))
