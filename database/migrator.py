import logging
import importlib
import pkgutil
import hashlib
from datetime import datetime, timezone
from typing import List, Dict, Any

from .connection import DatabaseConnectionPool

logger = logging.getLogger(__name__)

class MigrationStatus:
    def __init__(self, name: str, applied_at: str = None, checksum: str = None):
        self.name = name
        self.applied_at = applied_at
        self.checksum = checksum
        self.is_applied = applied_at is not None

class Migrator:
    """Runs database migrations in order."""
    
    def __init__(self, pool: DatabaseConnectionPool, migrations_pkg: str = "database.migrations"):
        self.pool = pool
        self.migrations_pkg = migrations_pkg
        self._ensure_migrations_table()
        
    def _ensure_migrations_table(self):
        with self.pool.get_write_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS _migrations (
                    name TEXT PRIMARY KEY,
                    applied_at TEXT NOT NULL,
                    checksum TEXT NOT NULL
                )
            """)
            
    def _get_applied_migrations(self) -> Dict[str, MigrationStatus]:
        with self.pool.get_read_connection() as conn:
            cursor = conn.execute("SELECT * FROM _migrations")
            return {
                row["name"]: MigrationStatus(row["name"], row["applied_at"], row["checksum"])
                for row in cursor.fetchall()
            }
            
    def _get_available_migrations(self) -> List[Any]:
        try:
            pkg = importlib.import_module(self.migrations_pkg)
        except ImportError:
            logger.warning(f"Migrations package {self.migrations_pkg} not found.")
            return []
            
        migrations = []
        for _, module_name, _ in pkgutil.iter_modules(pkg.__path__):
            mod = importlib.import_module(f"{self.migrations_pkg}.{module_name}")
            if hasattr(mod, "up") and hasattr(mod, "down"):
                # Use source code to generate a checksum
                import inspect
                source = inspect.getsource(mod)
                checksum = hashlib.sha256(source.encode()).hexdigest()
                migrations.append({
                    "name": module_name,
                    "up": mod.up,
                    "down": mod.down,
                    "checksum": checksum
                })
        
        # Sort alphabetically (so 001_..., 002_... run in order)
        migrations.sort(key=lambda x: x["name"])
        return migrations
        
    async def migrate(self) -> List[str]:
        """Apply all pending migrations."""
        applied = self._get_applied_migrations()
        available = self._get_available_migrations()
        
        just_applied = []
        
        for mig in available:
            name = mig["name"]
            
            if name in applied:
                if applied[name].checksum != mig["checksum"]:
                    logger.warning(f"Checksum mismatch for applied migration {name}!")
                continue
                
            logger.info(f"Applying migration: {name}")
            try:
                with self.pool.get_write_connection() as conn:
                    # Run the migration
                    mig["up"](conn)
                    
                    # Record it
                    conn.execute(
                        "INSERT INTO _migrations (name, applied_at, checksum) VALUES (?, ?, ?)",
                        (name, datetime.now(timezone.utc).isoformat(), mig["checksum"])
                    )
                just_applied.append(name)
            except Exception as e:
                logger.error(f"Migration {name} failed: {e}")
                raise
                
        return just_applied
        
    async def rollback(self, count: int = 1) -> List[str]:
        """Rollback the last N migrations."""
        applied = self._get_applied_migrations()
        if not applied:
            return []
            
        available = {m["name"]: m for m in self._get_available_migrations()}
        
        # Sort descending by name to rollback newest first
        applied_list = sorted(applied.keys(), reverse=True)
        to_rollback = applied_list[:count]
        
        just_rolled_back = []
        
        for name in to_rollback:
            if name not in available:
                logger.error(f"Cannot rollback {name}: migration script not found.")
                continue
                
            logger.info(f"Rolling back migration: {name}")
            try:
                with self.pool.get_write_connection() as conn:
                    available[name]["down"](conn)
                    conn.execute("DELETE FROM _migrations WHERE name = ?", (name,))
                just_rolled_back.append(name)
            except Exception as e:
                logger.error(f"Rollback of {name} failed: {e}")
                raise
                
        return just_rolled_back
