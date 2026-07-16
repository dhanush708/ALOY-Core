import logging
import importlib
import importlib.util
import hashlib
import sys
from pathlib import Path
from datetime import datetime, timezone
from typing import List, Dict, Any

from .connection import DatabaseConnectionPool

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════
# Migration Registry
#
# pkgutil.iter_modules() does NOT work inside a PyInstaller frozen bundle.
# The migrations are bundled as *data files* (not in PYZ), so they exist on
# disk at _internal/database/migrations/*.py, but the package __path__ is
# not correctly wired in the frozen importer.
#
# Fix: Use an explicit ordered list. To add a migration, append its name here.
# The Migrator will import it via importlib, falling back to file-based loading
# (importlib.util.spec_from_file_location) for frozen deployments.
# ═══════════════════════════════════════════════════════════════════════════

MIGRATION_NAMES: List[str] = [
    "001_initial",
    "002_security",
    "003_memory_tables",
    "004_vector_search",
    "005_conversation_tables",
    "006_prompt_registry",
    "007_reasoning_memory",
    "008_user_feedback",
    "009_advanced_memory",
    "010_project_management",
    "011_agent_tables",
    "012_telemetry",
    "013_evolution",
]

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
            
    def _import_migration_module(self, module_name: str):
        """Import a migration module — works in both normal and frozen mode."""
        full_name = f"{self.migrations_pkg}.{module_name}"

        # Tier 1: standard importlib (works in dev; may work in frozen if module is in PYZ)
        try:
            return importlib.import_module(full_name)
        except (ImportError, ModuleNotFoundError):
            pass

        # Tier 2: file-based loading (always works because migrations are bundled as datas)
        # In frozen mode:  _internal/database/migrations/<module_name>.py
        # In dev mode:     <project_root>/database/migrations/<module_name>.py
        if getattr(sys, "frozen", False):
            migration_file = Path(sys._MEIPASS) / "database" / "migrations" / f"{module_name}.py"
        else:
            # Derive path from the package location
            try:
                pkg = importlib.import_module(self.migrations_pkg)
                migration_file = Path(pkg.__file__).parent / f"{module_name}.py"
            except Exception:
                migration_file = Path("database") / "migrations" / f"{module_name}.py"

        if not migration_file.exists():
            logger.error(f"Migration file not found: {migration_file}")
            return None

        spec = importlib.util.spec_from_file_location(full_name, str(migration_file))
        mod = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(mod)
        except Exception as exc:
            logger.error(f"Failed to load migration {module_name} from {migration_file}: {exc}")
            return None

        return mod

    def _get_available_migrations(self) -> List[Any]:
        """Return all known migrations in order, using frozen-safe loading."""
        migrations = []
        for module_name in MIGRATION_NAMES:
            mod = self._import_migration_module(module_name)
            if mod is None:
                logger.warning(f"Skipping migration {module_name}: could not be loaded.")
                continue
            if not (hasattr(mod, "up") and hasattr(mod, "down")):
                logger.warning(f"Skipping {module_name}: missing up() or down() function.")
                continue

            # Compute checksum from source file content for reproducibility
            try:
                import inspect
                source = inspect.getsource(mod)
            except Exception:
                # Fallback: read file directly
                try:
                    file_path = getattr(mod, "__file__", None)
                    if file_path and Path(file_path).exists():
                        source = Path(file_path).read_text(encoding="utf-8")
                    else:
                        source = module_name  # last resort
                except Exception:
                    source = module_name

            checksum = hashlib.sha256(source.encode()).hexdigest()
            migrations.append({
                "name": module_name,
                "up": mod.up,
                "down": mod.down,
                "checksum": checksum,
            })

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
