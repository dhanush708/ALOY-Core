import logging
import json
import sqlite3
from dataclasses import dataclass
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone

from database.connection import DatabaseConnectionPool

logger = logging.getLogger(__name__)

@dataclass
class PromptTemplate:
    name: str
    version: str
    template: str
    variables: List[str]
    model_hint: str
    metadata: Dict[str, Any]
    
    def render(self, **kwargs) -> str:
        """Render prompt with variables."""
        missing = [v for v in self.variables if v not in kwargs]
        if missing:
            raise ValueError(f"Missing required prompt variables: {missing}")
        return self.template.format(**kwargs)

class PromptRegistry:
    """Centralized prompt management with database persistence and caching."""
    
    def __init__(self, db_pool: Optional[DatabaseConnectionPool] = None):
        self.db_pool = db_pool
        # Cache for fast retrieval: name -> {version -> PromptTemplate}
        self._cache: Dict[str, Dict[str, PromptTemplate]] = {}
        # Cache for active version string: name -> active_version
        self._active_cache: Dict[str, str] = {}
        
    async def start(self):
        logger.info("Prompt Registry started.")
        # Prepopulate cache on boot if database is available
        self._load_cache()
        
    async def stop(self):
        pass
        
    def _load_cache(self):
        """Prepopulate in-memory cache from database."""
        if not self.db_pool:
            return
            
        try:
            with self.db_pool.get_read_connection() as conn:
                cursor = conn.execute("SELECT * FROM prompts")
                rows = cursor.fetchall()
                for row in rows:
                    name = row["name"]
                    version = row["version"]
                    template = row["template"]
                    
                    try:
                        variables = json.loads(row["variables"]) if row["variables"] else []
                    except Exception:
                        variables = []
                        
                    try:
                        metadata = json.loads(row["metadata"]) if row["metadata"] else {}
                    except Exception:
                        metadata = {}
                        
                    model_hint = row["model_hint"] or "qwen3:8b"
                    
                    p = PromptTemplate(
                        name=name,
                        version=version,
                        template=template,
                        variables=variables,
                        model_hint=model_hint,
                        metadata=metadata
                    )
                    
                    if name not in self._cache:
                        self._cache[name] = {}
                    self._cache[name][version] = p
                    
                    if row["is_active"] == 1:
                        self._active_cache[name] = version
            logger.info("Prompts preloaded into registry cache.")
        except Exception as e:
            logger.error(f"Failed to preload prompts cache: {e}")

    def register(
        self,
        name: str,
        version: str,
        template: str,
        variables: List[str] = None,
        model_hint: str = "qwen3:8b",
        metadata: Dict[str, Any] = None,
        set_active: bool = True
    ) -> None:
        """Register a new prompt version."""
        variables = variables or []
        metadata = metadata or {}
        
        # 1. Update database if pool exists
        if self.db_pool:
            with self.db_pool.get_write_connection() as conn:
                # If set_active is True, clear active status for all other versions of this prompt
                if set_active:
                    conn.execute(
                        "UPDATE prompts SET is_active = 0 WHERE name = ?",
                        (name,)
                    )
                
                # Insert or replace the prompt
                is_active = 1 if set_active else 0
                created_at = datetime.now(timezone.utc).isoformat()
                
                conn.execute("""
                    INSERT INTO prompts (name, version, template, variables, model_hint, is_active, created_at, metadata)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(name, version) DO UPDATE SET
                        template=excluded.template,
                        variables=excluded.variables,
                        model_hint=excluded.model_hint,
                        is_active=excluded.is_active,
                        metadata=excluded.metadata
                """, (
                    name,
                    version,
                    template,
                    json.dumps(variables),
                    model_hint,
                    is_active,
                    created_at,
                    json.dumps(metadata)
                ))
        
        # 2. Update local cache
        p = PromptTemplate(
            name=name,
            version=version,
            template=template,
            variables=variables,
            model_hint=model_hint,
            metadata=metadata
        )
        
        if name not in self._cache:
            self._cache[name] = {}
        self._cache[name][version] = p
        
        if set_active or name not in self._active_cache:
            if set_active:
                self._active_cache[name] = version
            elif name not in self._active_cache:
                self._active_cache[name] = version
                
        logger.debug(f"Registered prompt {name} v{version}")
        
    def get(self, name: str, version: str = "latest") -> PromptTemplate:
        """Get a prompt by name and version."""
        # 1. Resolve version
        if version == "latest":
            cached_version = self._active_cache.get(name)
            if not cached_version and self.db_pool:
                with self.db_pool.get_read_connection() as conn:
                    row = conn.execute(
                        "SELECT version FROM prompts WHERE name = ? AND is_active = 1 LIMIT 1",
                        (name,)
                    ).fetchone()
                    if row:
                        cached_version = row["version"]
                        self._active_cache[name] = cached_version
            version = cached_version
            
        if not version:
            raise KeyError(f"No active version found for prompt '{name}'")
            
        # 2. Check cache
        if name in self._cache and version in self._cache[name]:
            return self._cache[name][version]
            
        # 3. Fallback to DB query if not in cache (cache miss)
        if self.db_pool:
            with self.db_pool.get_read_connection() as conn:
                row = conn.execute(
                    "SELECT * FROM prompts WHERE name = ? AND version = ?",
                    (name, version)
                ).fetchone()
                if row:
                    try:
                        variables = json.loads(row["variables"]) if row["variables"] else []
                    except Exception:
                        variables = []
                    try:
                        metadata = json.loads(row["metadata"]) if row["metadata"] else {}
                    except Exception:
                        metadata = {}
                    p = PromptTemplate(
                        name=row["name"],
                        version=row["version"],
                        template=row["template"],
                        variables=variables,
                        model_hint=row["model_hint"] or "qwen3:8b",
                        metadata=metadata
                    )
                    if name not in self._cache:
                        self._cache[name] = {}
                    self._cache[name][version] = p
                    return p
                    
        raise KeyError(f"Version '{version}' of prompt '{name}' not found")
        
    def list_versions(self, name: str) -> List[str]:
        """List all versions of a prompt."""
        if self.db_pool:
            try:
                with self.db_pool.get_read_connection() as conn:
                    cursor = conn.execute(
                        "SELECT version FROM prompts WHERE name = ?",
                        (name,)
                    )
                    return [r["version"] for r in cursor.fetchall()]
            except Exception as e:
                logger.error(f"Failed to list prompt versions: {e}")
                
        if name not in self._cache:
            return []
        return list(self._cache[name].keys())
        
    def set_active_version(self, name: str, version: str) -> None:
        """Change the active version of a prompt."""
        exists = False
        if name in self._cache and version in self._cache[name]:
            exists = True
        elif self.db_pool:
            with self.db_pool.get_read_connection() as conn:
                row = conn.execute(
                    "SELECT 1 FROM prompts WHERE name = ? AND version = ?",
                    (name, version)
                ).fetchone()
                if row:
                    exists = True
                    
        if not exists:
            raise KeyError(f"Prompt '{name}' v{version} not found")
            
        if self.db_pool:
            with self.db_pool.get_write_connection() as conn:
                conn.execute(
                    "UPDATE prompts SET is_active = 0 WHERE name = ?",
                    (name,)
                )
                conn.execute(
                    "UPDATE prompts SET is_active = 1 WHERE name = ? AND version = ?",
                    (name, version)
                )
                
        self._active_cache[name] = version
        logger.info(f"Set active version of {name} to {version}")
        
    def record_metric(self, name: str, version: str, metric_name: str, value: float) -> None:
        """Record performance/evaluation metrics for a prompt version."""
        if not self.db_pool:
            return
            
        try:
            with self.db_pool.get_write_connection() as conn:
                conn.execute("""
                    INSERT INTO prompt_metrics (prompt_name, prompt_version, metric_name, metric_value, sample_count, measured_at)
                    VALUES (?, ?, ?, ?, 1, ?)
                    ON CONFLICT(prompt_name, prompt_version, metric_name) DO UPDATE SET
                        metric_value = (prompt_metrics.metric_value * prompt_metrics.sample_count + excluded.metric_value) / (prompt_metrics.sample_count + 1),
                        sample_count = prompt_metrics.sample_count + 1,
                        measured_at = excluded.measured_at
                """, (
                    name,
                    version,
                    metric_name,
                    value,
                    datetime.now(timezone.utc).isoformat()
                ))
            logger.debug(f"Recorded metric {metric_name}={value} for prompt {name} v{version}")
        except Exception as e:
            logger.error(f"Failed to record prompt metric: {e}")
