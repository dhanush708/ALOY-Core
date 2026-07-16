import hashlib
import json
import logging
import time
from datetime import datetime, timezone
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

class ResearchCache:
    """Persistent SQLite-backed cache for general web search results with TTL support."""

    def __init__(self, db_pool, ttl_seconds: int = 600):
        self.db_pool = db_pool
        self.ttl_seconds = ttl_seconds
        self._ensure_cache_table()

    def _ensure_cache_table(self):
        """Create the research cache table if it does not exist."""
        try:
            with self.db_pool.get_write_connection() as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS research_cache (
                        key          TEXT PRIMARY KEY,
                        query        TEXT NOT NULL,
                        results_json TEXT NOT NULL,
                        created_at   INTEGER NOT NULL
                    )
                """)
                conn.execute("CREATE INDEX IF NOT EXISTS idx_res_cache_created ON research_cache(created_at)")
        except Exception as e:
            logger.error(f"Failed to initialize research cache table: {e}")

    def _generate_key(self, query: str) -> str:
        """Generate a lookup hash."""
        return hashlib.sha256(query.strip().lower().encode("utf-8")).hexdigest()

    def get(self, query: str) -> Optional[Dict[str, Any]]:
        """Fetch cached query results if within TTL bounds."""
        key = self._generate_key(query)
        now_ts = int(time.time())
        cutoff = now_ts - self.ttl_seconds
        
        try:
            with self.db_pool.get_write_connection() as conn:
                conn.execute("DELETE FROM research_cache WHERE created_at < ?", (cutoff,))
                
                cursor = conn.execute("SELECT results_json FROM research_cache WHERE key = ?", (key,))
                row = cursor.fetchone()
                if row:
                    return json.loads(row["results_json"])
        except Exception as e:
            logger.error(f"Failed to get from research cache: {e}")
        return None

    def set(self, query: str, results_data: Dict[str, Any]) -> None:
        """Cache search results with current timestamp."""
        key = self._generate_key(query)
        now_ts = int(time.time())
        resp_str = json.dumps(results_data)

        try:
            with self.db_pool.get_write_connection() as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO research_cache (key, query, results_json, created_at)
                    VALUES (?, ?, ?, ?)
                """, (key, query, resp_str, now_ts))
        except Exception as e:
            logger.error(f"Failed to set research cache: {e}")

    def get_size(self) -> int:
        """Get count of active cached items."""
        try:
            with self.db_pool.get_read_connection() as conn:
                cursor = conn.execute("SELECT COUNT(*) as cnt FROM research_cache")
                return cursor.fetchone()["cnt"]
        except Exception:
            return 0

    def clear(self) -> None:
        """Clear cache completely."""
        try:
            with self.db_pool.get_write_connection() as conn:
                conn.execute("DELETE FROM research_cache")
        except Exception as e:
            logger.error(f"Failed to clear research cache: {e}")
