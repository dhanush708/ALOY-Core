import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

class DocCache:
    """Persistent database-backed cache for documentation summaries and examples."""

    def __init__(self, db_pool):
        self.db_pool = db_pool
        self._ensure_cache_table()

    def _ensure_cache_table(self):
        """Create the cache table if it does not exist."""
        try:
            with self.db_pool.get_write_connection() as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS documentation_cache (
                        key              TEXT PRIMARY KEY,
                        query            TEXT NOT NULL,
                        package          TEXT NOT NULL,
                        version          TEXT NOT NULL,
                        response_json    TEXT NOT NULL,
                        created_at       TEXT NOT NULL,
                        last_accessed_at TEXT NOT NULL
                    )
                """)
                conn.execute("CREATE INDEX IF NOT EXISTS idx_doc_cache_accessed ON documentation_cache(last_accessed_at)")
        except Exception as e:
            logger.error(f"Failed to initialize documentation cache table: {e}")

    def _generate_key(self, query: str, package: str, version: str) -> str:
        """Generate a unique lookup key."""
        raw = f"{query.strip().lower()}:{package.strip().lower()}:{version.strip().lower()}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def get(self, query: str, package: str, version: str) -> Optional[Dict[str, Any]]:
        """Retrieve a cached response, updating its access timestamp."""
        key = self._generate_key(query, package, version)
        now = datetime.now(timezone.utc).isoformat()
        
        try:
            with self.db_pool.get_write_connection() as conn:
                conn.execute("UPDATE documentation_cache SET last_accessed_at = ? WHERE key = ?", (now, key))
                cursor = conn.execute("SELECT response_json FROM documentation_cache WHERE key = ?", (key,))
                row = cursor.fetchone()
                if row:
                    return json.loads(row["response_json"])
        except Exception as e:
            logger.error(f"Failed to get from doc cache: {e}")
        return None

    def set(self, query: str, package: str, version: str, response_data: Dict[str, Any]) -> None:
        """Insert or replace a cache entry, and run a size prune check."""
        key = self._generate_key(query, package, version)
        now = datetime.now(timezone.utc).isoformat()
        resp_str = json.dumps(response_data)

        try:
            with self.db_pool.get_write_connection() as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO documentation_cache (key, query, package, version, response_json, created_at, last_accessed_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (key, query, package, version, resp_str, now, now))
            
            self.prune(max_size=500)
        except Exception as e:
            logger.error(f"Failed to set doc cache: {e}")

    def prune(self, max_size: int = 500) -> None:
        """Remove least recently used entries if cache size exceeds limit."""
        try:
            with self.db_pool.get_write_connection() as conn:
                cursor = conn.execute("SELECT COUNT(*) as cnt FROM documentation_cache")
                count = cursor.fetchone()["cnt"]
                if count > max_size:
                    to_delete = count - max_size
                    conn.execute(f"""
                        DELETE FROM documentation_cache 
                        WHERE key IN (
                            SELECT key FROM documentation_cache 
                            ORDER BY last_accessed_at ASC 
                            LIMIT ?
                        )
                    """, (to_delete,))
                    logger.info(f"Pruned {to_delete} entries from documentation cache.")
        except Exception as e:
            logger.error(f"Failed to prune doc cache: {e}")

    def clear(self) -> None:
        """Clear the entire cache."""
        try:
            with self.db_pool.get_write_connection() as conn:
                conn.execute("DELETE FROM documentation_cache")
                logger.info("Documentation cache cleared.")
        except Exception as e:
            logger.error(f"Failed to clear doc cache: {e}")
