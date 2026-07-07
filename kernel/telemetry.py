import logging
import json
import asyncio
import time
import os
import threading
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional
from kernel.types import Event

logger = logging.getLogger(__name__)

class MetricPoint:
    def __init__(self, metric: str, value: float, tags: Dict[str, str], timestamp: Optional[datetime] = None):
        self.metric = metric
        self.value = value
        self.tags = tags
        self.timestamp = timestamp or datetime.now(timezone.utc)
        
    def to_dict(self) -> Dict[str, Any]:
        return {
            "metric": self.metric,
            "value": self.value,
            "tags": self.tags,
            "timestamp": self.timestamp.isoformat()
        }

class Telemetry:
    """Collects structured metrics from all subsystems and persists them to SQLite."""
    
    def __init__(self, db_pool=None, event_bus=None):
        self.db_pool = db_pool
        self.event_bus = event_bus
        self._buffer: List[MetricPoint] = []
        self._lock = threading.Lock()
        
        self._stop_event = asyncio.Event()
        self._flush_task: Optional[asyncio.Task] = None
        self._last_agg_time = 0
        self._last_sys_res_time = 0
        
    async def start(self):
        self._stop_event.clear()
        
        # Subscribe to relevant event bus events
        if self.event_bus:
            self.event_bus.subscribe("tool.completed", self._on_tool_completed)
            self.event_bus.subscribe("tool.failed", self._on_tool_failed)
            self.event_bus.subscribe("agent.step.completed", self._on_agent_step_completed)
            self.event_bus.subscribe("agent.step.failed", self._on_agent_step_failed)
            logger.info("Telemetry system registered to event bus subscriptions.")
            
        self._flush_task = asyncio.create_task(self._periodic_loop())
        logger.info("Telemetry system started.")
        
    async def stop(self):
        self._stop_event.set()
        if self._flush_task:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass
        await self.flush()
        logger.info("Telemetry system stopped.")
        
    def record_latency(self, operation: str, duration_ms: float, tags: Dict[str, str] = None):
        """Record the latency of an operation."""
        _tags = tags or {}
        _tags["operation"] = operation
        with self._lock:
            self._buffer.append(MetricPoint("system.latency_ms", duration_ms, _tags))
            
    def record_counter(self, metric: str, value: int = 1, tags: Dict[str, str] = None):
        """Record a generic counter metric."""
        with self._lock:
            self._buffer.append(MetricPoint(metric, float(value), tags or {}))
            
    def record_model_call(self, model: str, task: str, tokens_in: int, tokens_out: int, latency_ms: float):
        """Record specific model usage metrics."""
        tags = {"model": model, "task": task}
        self.record_counter("llm.tokens_in", tokens_in, tags)
        self.record_counter("llm.tokens_out", tokens_out, tags)
        self.record_latency("llm.inference", latency_ms, tags)
        
    def record_memory_retrieval(self, query: str, results: int, latency_ms: float, method: str):
        """Record memory retrieval metrics."""
        tags = {"method": method}
        self.record_latency("memory.retrieval", latency_ms, tags)
        self.record_counter("memory.retrieved_count", results, tags)
        
    def record_system_resources(self):
        """Record process RSS memory usage."""
        try:
            import psutil
            process = psutil.Process(os.getpid())
            mem_mb = process.memory_info().rss / (1024 * 1024)
            self.record_counter("system.memory_mb", mem_mb)
        except ImportError:
            # Fallback if psutil is not installed
            pass
            
    async def flush(self):
        """Flush buffered metrics to database."""
        with self._lock:
            if not self._buffer:
                return
            points_to_flush = list(self._buffer)
            self._buffer.clear()
            
        if not self.db_pool:
            logger.debug(f"Telemetry db_pool not configured. Dropped {len(points_to_flush)} metrics.")
            return
            
        try:
            with self.db_pool.get_write_connection() as conn:
                for pt in points_to_flush:
                    conn.execute(
                        "INSERT INTO telemetry (metric, value, tags, timestamp) VALUES (?, ?, ?, ?)",
                        (pt.metric, pt.value, json.dumps(pt.tags), pt.timestamp.isoformat())
                    )
            logger.debug(f"Flushed {len(points_to_flush)} telemetry metrics to DB")
        except Exception as e:
            logger.error(f"Failed to flush telemetry metrics to database: {e}")
            
    async def aggregate_metrics(self):
        """Aggregate raw metrics into hourly and daily telemetry_aggregates."""
        if not self.db_pool:
            return
            
        now = datetime.now(timezone.utc)
        one_day_ago = (now - timedelta(days=1)).isoformat()
        thirty_days_ago = (now - timedelta(days=30)).isoformat()
        
        try:
            with self.db_pool.get_write_connection() as conn:
                # 1. Hourly aggregation (last 24 hours)
                cursor = conn.execute("""
                    SELECT metric,
                           strftime('%Y-%m-%dT%H:00:00', timestamp) as period_start,
                           avg(value) as avg_val,
                           min(value) as min_val,
                           max(value) as max_val,
                           count(value) as cnt
                    FROM telemetry
                    WHERE timestamp >= ?
                    GROUP BY metric, period_start
                """, (one_day_ago,))
                
                for r in cursor.fetchall():
                    conn.execute("""
                        INSERT OR REPLACE INTO telemetry_aggregates (metric, period, period_start, avg_value, min_value, max_value, count)
                        VALUES (?, 'hourly', ?, ?, ?, ?, ?)
                    """, (r["metric"], r["period_start"], r["avg_val"], r["min_val"], r["max_val"], r["cnt"]))
                    
                # 2. Daily aggregation (last 30 days)
                cursor = conn.execute("""
                    SELECT metric,
                           strftime('%Y-%m-%dT00:00:00', timestamp) as period_start,
                           avg(value) as avg_val,
                           min(value) as min_val,
                           max(value) as max_val,
                           count(value) as cnt
                    FROM telemetry
                    WHERE timestamp >= ?
                    GROUP BY metric, period_start
                """, (thirty_days_ago,))
                
                for r in cursor.fetchall():
                    conn.execute("""
                        INSERT OR REPLACE INTO telemetry_aggregates (metric, period, period_start, avg_value, min_value, max_value, count)
                        VALUES (?, 'daily', ?, ?, ?, ?, ?)
                    """, (r["metric"], r["period_start"], r["avg_val"], r["min_val"], r["max_val"], r["cnt"]))
            logger.info("Metrics aggregation successfully computed.")
        except Exception as e:
            logger.error(f"Error during metrics aggregation: {e}")
            
    async def cleanup_old_metrics(self):
        """Enforce retention limits: raw metrics kept 7 days, aggregates kept 90 days."""
        if not self.db_pool:
            return
            
        now = datetime.now(timezone.utc)
        seven_days_ago = (now - timedelta(days=7)).isoformat()
        ninety_days_ago = (now - timedelta(days=90)).isoformat()
        
        try:
            with self.db_pool.get_write_connection() as conn:
                cursor1 = conn.execute("DELETE FROM telemetry WHERE timestamp < ?", (seven_days_ago,))
                cursor2 = conn.execute("DELETE FROM telemetry_aggregates WHERE period_start < ?", (ninety_days_ago,))
                logger.info(f"Cleaned up old metrics: deleted {cursor1.rowcount} raw rows, {cursor2.rowcount} aggregates.")
        except Exception as e:
            logger.error(f"Error during metrics retention cleanup: {e}")
            
    def get_buffered_metrics(self) -> List[Dict[str, Any]]:
        """Get metrics still in memory buffer."""
        with self._lock:
            return [p.to_dict() for p in self._buffer]
            
    async def _periodic_loop(self):
        """Background loop executing flush, system resource logging, aggregates, and cleanup."""
        self._last_agg_time = time.time()
        self._last_sys_res_time = time.time()
        
        while not self._stop_event.is_set():
            try:
                # Sleep in a fine-grained loop so we can exit quickly
                for _ in range(50):
                    if self._stop_event.is_set():
                        break
                    await asyncio.sleep(0.1)
                    
                if self._stop_event.is_set():
                    break
                    
                await self.flush()
                
                # Log resources every 30 seconds
                now_t = time.time()
                if now_t - self._last_sys_res_time >= 30:
                    self.record_system_resources()
                    self._last_sys_res_time = now_t
                    
                # Hourly aggregates and cleanup (abridged to 60s check for responsiveness)
                if now_t - self._last_agg_time >= 60:
                    await self.aggregate_metrics()
                    await self.cleanup_old_metrics()
                    self._last_agg_time = now_t
                    
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in telemetry background loop: {e}")
                await asyncio.sleep(5)
                
    # ------------------------------------------------------------------
    # Event Handlers
    # ------------------------------------------------------------------
    def _on_tool_completed(self, event: Event):
        tool_name = event.data.get("tool_name", "unknown")
        duration_ms = float(event.data.get("duration_ms", 0.0))
        self.record_latency(f"tool.{tool_name}", duration_ms, {"status": "success", "tool_name": tool_name})
        self.record_counter("tool.execution", 1, {"status": "success", "tool_name": tool_name})
        
    def _on_tool_failed(self, event: Event):
        tool_name = event.data.get("tool_name", "unknown")
        duration_ms = float(event.data.get("duration_ms", 0.0))
        self.record_latency(f"tool.{tool_name}", duration_ms, {"status": "failed", "tool_name": tool_name})
        self.record_counter("tool.execution", 1, {"status": "failed", "tool_name": tool_name})
        
    def _on_agent_step_completed(self, event: Event):
        step_type = event.data.get("step_type", "unknown")
        duration_ms = float(event.data.get("duration_ms", 0.0))
        self.record_latency(f"agent.step.{step_type}", duration_ms, {"status": "success", "step_type": step_type})
        self.record_counter("agent.steps", 1, {"status": "success", "step_type": step_type})
        
    def _on_agent_step_failed(self, event: Event):
        step_type = event.data.get("step_type", "unknown")
        duration_ms = float(event.data.get("duration_ms", 0.0))
        self.record_latency(f"agent.step.{step_type}", duration_ms, {"status": "failed", "step_type": step_type})
        self.record_counter("agent.steps", 1, {"status": "failed", "step_type": step_type})
