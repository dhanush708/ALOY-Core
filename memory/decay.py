import logging
import math
from datetime import datetime, timezone
from typing import Tuple

logger = logging.getLogger(__name__)

class DecayEngine:
    """Applies exponential decay to memories over time."""
    
    def __init__(self, db_pool, archival_threshold: float = 0.1):
        self.db_pool = db_pool
        self.archival_threshold = archival_threshold
        
    async def process_decay(self) -> Tuple[int, int]:
        """
        Updates the importance of all memories based on decay rate.
        Archives those that fall below threshold.
        Returns: (num_decayed, num_archived)
        """
        now = datetime.now(timezone.utc)
        now_iso = now.isoformat()
        
        decayed = 0
        archived = 0
        
        try:
            with self.db_pool.get_write_connection() as conn:
                # 1. Archive items that have dropped below threshold (and are not protected/permanent)
                # First we must calculate the effective importance in SQL
                # Since SQLite doesn't have math.exp, we decay in Python for the archival check,
                # or we just do a simpler linear approximation in SQL, or we pull and update.
                
                # Because we want true exponential decay, we pull the candidates, calc in python, and bulk update.
                # To be efficient, we only pull active memories.
                cursor = conn.execute("""
                    SELECT id, importance, decay_rate, last_accessed_at, created_at, is_protected
                    FROM memories
                    WHERE archived_at IS NULL
                      AND tier != 'permanent'
                """)
                
                rows = cursor.fetchall()
                updates = []
                archives = []
                
                for row in rows:
                    if row["is_protected"]:
                        continue
                        
                    last_time_str = row["last_accessed_at"] or row["created_at"]
                    try:
                        last_time = datetime.fromisoformat(last_time_str)
                        hours = max(0, (now - last_time).total_seconds() / 3600.0)
                    except Exception:
                        continue
                        
                    decay_rate = row["decay_rate"]
                    if decay_rate <= 0:
                        continue
                        
                    # Calculate new effective importance
                    current_importance = row["importance"]
                    new_importance = current_importance * math.exp(-decay_rate * hours)
                    
                    if new_importance < self.archival_threshold:
                        archives.append((now_iso, row["id"]))
                    else:
                        # Only update if it significantly changed (e.g. > 5%)
                        if (current_importance - new_importance) > 0.05:
                            updates.append((new_importance, row["id"]))
                
                # Apply updates
                if updates:
                    conn.executemany("UPDATE memories SET importance = ? WHERE id = ?", updates)
                    decayed = len(updates)
                    
                if archives:
                    conn.executemany("UPDATE memories SET archived_at = ? WHERE id = ?", archives)
                    archived = len(archives)
                    
        except Exception as e:
            logger.error(f"Error processing memory decay: {e}")
            
        return decayed, archived
