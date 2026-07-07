import pytest
import pytest_asyncio
import asyncio
import sqlite3
import json
from datetime import datetime, timezone, timedelta
from fastapi.testclient import TestClient

from api.server import app
from database.connection import DatabaseConnectionPool
from database.migrator import Migrator
from kernel.telemetry import Telemetry, MetricPoint
from kernel.event_bus import EventBus
from kernel.types import Event

@pytest_asyncio.fixture
async def telemetry_test_env(tmp_path):
    db_path = str(tmp_path / "test_telemetry.db")
    pool = DatabaseConnectionPool(db_path)
    await pool.start()
    
    migrator = Migrator(pool, migrations_pkg="database.migrations")
    await migrator.migrate()
    
    bus = EventBus()
    await bus.start()
    
    telemetry = Telemetry(pool, bus)
    await telemetry.start()
    
    # Save original app.state
    orig_db = getattr(app.state, "db_pool", None)
    orig_tel = getattr(app.state, "telemetry", None)
    
    app.state.db_pool = pool
    app.state.telemetry = telemetry
    
    yield pool, telemetry, bus
    
    # Restore and stop
    app.state.db_pool = orig_db
    app.state.telemetry = orig_tel
    
    await telemetry.stop()
    await bus.stop()
    await pool.stop()

@pytest.mark.asyncio
async def test_telemetry_recording_and_flushing(telemetry_test_env):
    pool, telemetry, bus = telemetry_test_env
    
    # 1. Record various metrics
    telemetry.record_latency("test.latency", 123.4, {"tag1": "val1"})
    telemetry.record_counter("test.counter", 5, {"tag2": "val2"})
    telemetry.record_model_call("phi4-mini:latest", "classification", 10, 20, 250.0)
    telemetry.record_memory_retrieval("test query", 3, 45.0, "hybrid")
    telemetry.record_system_resources()
    
    # Check buffer
    buffered = telemetry.get_buffered_metrics()
    assert len(buffered) >= 5 # latency, counter, 2 for model call (tokens in/out) + latency, retrieval, resources
    
    # 2. Flush
    await telemetry.flush()
    assert len(telemetry.get_buffered_metrics()) == 0
    
    # 3. Verify in DB
    with pool.get_read_connection() as conn:
        cursor = conn.execute("SELECT * FROM telemetry")
        rows = [dict(r) for r in cursor.fetchall()]
        
    metrics = [r["metric"] for r in rows]
    assert "system.latency_ms" in metrics
    assert "test.counter" in metrics
    assert "llm.tokens_in" in metrics
    assert "llm.tokens_out" in metrics
    assert "memory.retrieved_count" in metrics

@pytest.mark.asyncio
async def test_telemetry_aggregation(telemetry_test_env):
    pool, telemetry, bus = telemetry_test_env
    
    now = datetime.now(timezone.utc)
    # Insert custom older metrics directly in DB
    h1 = (now - timedelta(hours=2)).isoformat()
    h2 = (now - timedelta(hours=3)).isoformat()
    
    with pool.get_write_connection() as conn:
        conn.execute(
            "INSERT INTO telemetry (metric, value, tags, timestamp) VALUES (?, ?, ?, ?)",
            ("agg.test", 10.0, '{"type": "h1"}', h1)
        )
        conn.execute(
            "INSERT INTO telemetry (metric, value, tags, timestamp) VALUES (?, ?, ?, ?)",
            ("agg.test", 20.0, '{"type": "h2"}', h1)
        )
        conn.execute(
            "INSERT INTO telemetry (metric, value, tags, timestamp) VALUES (?, ?, ?, ?)",
            ("agg.test", 30.0, '{"type": "h3"}', h2)
        )
        
    await telemetry.aggregate_metrics()
    
    # Verify aggregates
    with pool.get_read_connection() as conn:
        cursor = conn.execute("SELECT * FROM telemetry_aggregates WHERE metric = 'agg.test'")
        rows = [dict(r) for r in cursor.fetchall()]
        
    assert len(rows) >= 2 # 2 hourly blocks, plus daily blocks
    hourly_rows = [r for r in rows if r["period"] == "hourly"]
    assert len(hourly_rows) == 2
    
    # Check values for h1 period (which has 2 entries: 10.0 and 20.0, avg should be 15.0)
    h1_agg = [r for r in hourly_rows if r["count"] == 2]
    assert len(h1_agg) == 1
    assert h1_agg[0]["avg_value"] == 15.0
    assert h1_agg[0]["min_value"] == 10.0
    assert h1_agg[0]["max_value"] == 20.0
    
    # Check values for h2 period (which has 1 entry: 30.0, avg should be 30.0)
    h2_agg = [r for r in hourly_rows if r["count"] == 1]
    assert len(h2_agg) == 1
    assert h2_agg[0]["avg_value"] == 30.0

@pytest.mark.asyncio
async def test_telemetry_cleanup(telemetry_test_env):
    pool, telemetry, bus = telemetry_test_env
    
    now = datetime.now(timezone.utc)
    old_raw = (now - timedelta(days=8)).isoformat()
    new_raw = (now - timedelta(days=3)).isoformat()
    
    old_agg = (now - timedelta(days=95)).isoformat()
    new_agg = (now - timedelta(days=45)).isoformat()
    
    with pool.get_write_connection() as conn:
        # Raw metrics
        conn.execute(
            "INSERT INTO telemetry (metric, value, tags, timestamp) VALUES (?, ?, ?, ?)",
            ("cleanup.raw", 1.0, '{}', old_raw)
        )
        conn.execute(
            "INSERT INTO telemetry (metric, value, tags, timestamp) VALUES (?, ?, ?, ?)",
            ("cleanup.raw", 2.0, '{}', new_raw)
        )
        
        # Aggregates
        conn.execute(
            "INSERT INTO telemetry_aggregates (metric, period, period_start, avg_value, min_value, max_value, count) "
            "VALUES (?, 'daily', ?, ?, ?, ?, ?)",
            ("cleanup.agg", old_agg, 1.0, 1.0, 1.0, 1)
        )
        conn.execute(
            "INSERT INTO telemetry_aggregates (metric, period, period_start, avg_value, min_value, max_value, count) "
            "VALUES (?, 'daily', ?, ?, ?, ?, ?)",
            ("cleanup.agg", new_agg, 2.0, 2.0, 2.0, 1)
        )
        
    await telemetry.cleanup_old_metrics()
    
    # Verify what remains
    with pool.get_read_connection() as conn:
        raw_rows = conn.execute("SELECT * FROM telemetry WHERE metric = 'cleanup.raw'").fetchall()
        agg_rows = conn.execute("SELECT * FROM telemetry_aggregates WHERE metric = 'cleanup.agg'").fetchall()
        
    assert len(raw_rows) == 1
    assert raw_rows[0]["timestamp"] == new_raw
    
    assert len(agg_rows) == 1
    assert agg_rows[0]["period_start"] == new_agg

@pytest.mark.asyncio
async def test_telemetry_event_listeners(telemetry_test_env):
    pool, telemetry, bus = telemetry_test_env
    
    # Trigger tool completed event
    await bus.publish(Event(
        type="tool.completed",
        data={"tool_name": "TerminalTool", "duration_ms": 150.0},
        source="tools"
    ))
    
    # Trigger agent step failed event
    await bus.publish(Event(
        type="agent.step.failed",
        data={"step_type": "coding", "duration_ms": 3000.0},
        source="agent"
    ))
    
    await asyncio.sleep(0.1) # allow handler tasks to run
    await telemetry.flush()
    
    with pool.get_read_connection() as conn:
        rows = conn.execute("SELECT * FROM telemetry").fetchall()
        
    metrics = [r["metric"] for r in rows]
    assert "system.latency_ms" in metrics
    assert "tool.execution" in metrics
    assert "agent.steps" in metrics

def test_telemetry_api_endpoints(telemetry_test_env):
    client = TestClient(app)
    
    # 1. Test POST /api/system/metrics/aggregate
    response = client.post("/api/system/metrics/aggregate")
    assert response.status_code == 200
    assert response.json()["status"] == "success"
    
    # 2. Test POST /api/system/metrics/cleanup
    response = client.post("/api/system/metrics/cleanup")
    assert response.status_code == 200
    assert response.json()["status"] == "success"
    
    # 3. Seed some dummy values for dashboard stats
    pool = app.state.db_pool
    now = datetime.now(timezone.utc).isoformat()
    with pool.get_write_connection() as conn:
        conn.execute(
            "INSERT INTO telemetry (metric, value, tags, timestamp) VALUES (?, ?, ?, ?)",
            ("system.latency_ms", 150.0, '{"operation": "llm.inference"}', now)
        )
        conn.execute(
            "INSERT INTO telemetry (metric, value, tags, timestamp) VALUES (?, ?, ?, ?)",
            ("llm.tokens_in", 100, '{}', now)
        )
        conn.execute(
            "INSERT INTO telemetry (metric, value, tags, timestamp) VALUES (?, ?, ?, ?)",
            ("llm.tokens_out", 50, '{}', now)
        )
        conn.execute(
            "INSERT INTO telemetry (metric, value, tags, timestamp) VALUES (?, ?, ?, ?)",
            ("system.latency_ms", 20.0, '{"operation": "memory.retrieval"}', now)
        )
        conn.execute(
            "INSERT INTO telemetry (metric, value, tags, timestamp) VALUES (?, ?, ?, ?)",
            ("memory.cache_hit", 1, '{}', now)
        )
        conn.execute(
            "INSERT INTO telemetry (metric, value, tags, timestamp) VALUES (?, ?, ?, ?)",
            ("memory.cache_miss", 1, '{}', now)
        )
        
    # 4. Test GET /api/system/dashboard/stats
    response = client.get("/api/system/dashboard/stats")
    assert response.status_code == 200
    data = response.json()
    assert data["llm_calls_count"] == 1
    assert data["avg_llm_latency_ms"] == 150.0
    assert data["total_tokens_in"] == 100
    assert data["total_tokens_out"] == 50
    assert data["memory_retrievals_count"] == 1
    assert data["avg_memory_retrieval_ms"] == 20.0
    assert data["memory_cache_hit_rate"] == 0.5
    
    # 5. Test GET /api/system/metrics
    response = client.get("/api/system/metrics?metric=llm.tokens_in")
    assert response.status_code == 200
    results = response.json()
    assert len(results) == 1
    assert results[0]["metric"] == "llm.tokens_in"
    assert results[0]["value"] == 100.0
