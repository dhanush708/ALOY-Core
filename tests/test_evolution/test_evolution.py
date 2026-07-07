import pytest
import pytest_asyncio
import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from fastapi.testclient import TestClient

# Globally mock EmbeddingEngine
import memory.embeddings
memory.embeddings.EmbeddingEngine.generate = AsyncMock(return_value=[0.1] * 768)
memory.embeddings.EmbeddingEngine.generate_batch = AsyncMock(return_value=[[0.1] * 768])

from api.server import app
from database.connection import DatabaseConnectionPool
from database.migrator import Migrator
from memory.manager import MemoryManager
from kernel.prompts import PromptRegistry
from evolution.service import EvolutionEngine


@pytest_asyncio.fixture
async def evolution_test_env(tmp_path):
    db_path = str(tmp_path / "test_evolution.db")
    pool = DatabaseConnectionPool(db_path)
    await pool.start()

    migrator = Migrator(pool, migrations_pkg="database.migrations")
    await migrator.migrate()

    memory_mgr = MemoryManager(pool)
    await memory_mgr.start()

    # Mock ModelRouter
    mock_router = MagicMock()
    mock_router.tracker = MagicMock()
    mock_router.tracker._calls = {}
    mock_router.tracker._errors = {}
    mock_router.tracker._latencies = {}

    # Setup prompt templates returns
    async def mock_generate(task, prompt, options=None, conversation_id=None):
        if "overlapping semantic/permanent memories" in prompt:
            return json.dumps({
                "problem": "Duplicate configuration memories.",
                "evidence": "Memory overlap.",
                "possible_solutions": ["Merge duplicate entries"],
                "recommended_solution": "Consolidated memory details.",
                "affected_files": ["database:memories"],
                "benefits": "Smaller context size",
                "risks": "None",
                "implementation_plan": "- [ ] Delete old\n- [ ] Store new"
            })
        elif "repeated task failure" in prompt:
            return json.dumps({
                "problem": "Repeated debugger failures due to syntax error.",
                "evidence": "Failing 2 times.",
                "possible_solutions": ["Fix debugger regex parser", "Skip bad files"],
                "recommended_solution": "Fix debugger regex parser",
                "affected_files": ["agent/agents/debugger.py"],
                "benefits": "Cleaner task execution",
                "risks": "Minimal risk",
                "implementation_plan": "- [ ] Fix code\n- [ ] Run tests"
            })
        elif "prompt drift" in prompt:
            return json.dumps({
                "problem": "Prompt routing is leading to long latency.",
                "evidence": "Average latency > 15s.",
                "possible_solutions": ["Shorten phi4 instructions"],
                "recommended_solution": "Optimized template prompt instruction.",
                "affected_files": ["database:prompts"],
                "benefits": "Faster inferences",
                "risks": "None",
                "implementation_plan": "- [ ] Register template"
            })
        elif "missing dependency issue" in prompt:
            return json.dumps({
                "problem": "Missing requests module.",
                "evidence": "ModuleNotFoundError.",
                "possible_solutions": ["pip install requests"],
                "recommended_solution": "pip install requests",
                "affected_files": ["requirements.txt"],
                "benefits": "Allows agent web fetching",
                "risks": "None",
                "implementation_plan": "- [ ] Install package"
            })
        return "{}"

    mock_router.generate = AsyncMock(side_effect=mock_generate)

    # Prompt registry
    prompt_reg = PromptRegistry(pool)
    await prompt_reg.start()

    # Agent Runtime mock
    mock_runtime = MagicMock()
    mock_runtime.start_session = AsyncMock(return_value="test_session_id")
    mock_runtime.execute_session = AsyncMock()

    # Evolution Engine
    engine = EvolutionEngine(
        db_pool=pool,
        memory_manager=memory_mgr,
        model_router=mock_router,
        model_tracker=mock_router.tracker,
        prompt_registry=prompt_reg,
        agent_runtime=mock_runtime
    )
    await engine.start()

    # Seed data
    # 1. Seed overlapping memories
    await memory_mgr.store(
        type="semantic",
        content="System uses phi4-mini as primary classifier for routing tasks.",
        tier="permanent"
    )
    await memory_mgr.store(
        type="semantic",
        content="System uses phi4-mini as primary classifier for routing tasks.",
        tier="permanent"
    )

    # 2. Seed repeated failure tasks
    now = "2026-06-23T12:00:00"
    with pool.get_write_connection() as conn:
        conn.execute("INSERT INTO projects (id, name, root_path, created_at, updated_at) VALUES ('p1', 'TestProj', 'tmp', ?, ?)", (now, now))
        conn.execute("INSERT INTO agent_sessions (id, project_id, goal, status, created_at, updated_at) VALUES ('s1', 'p1', 'goal', 'planning', ?, ?)", (now, now))
        
        # Insert failing tasks
        conn.execute("""
            INSERT INTO agent_tasks (id, session_id, assigned_agent, title, description, status, error, created_at, updated_at)
            VALUES ('t1', 's1', 'debugger', 'Fix Regex Parser', 'desc', 'failed', 'RegexSyntaxError', ?, ?)
        """, (now, now))
        conn.execute("""
            INSERT INTO agent_tasks (id, session_id, assigned_agent, title, description, status, error, created_at, updated_at)
            VALUES ('t2', 's1', 'debugger', 'Fix Regex Parser', 'desc', 'failed', 'RegexSyntaxError', ?, ?)
        """, (now, now))

        # 3. Seed missing dependency failure
        conn.execute("""
            INSERT INTO agent_tasks (id, session_id, assigned_agent, title, description, status, error, created_at, updated_at)
            VALUES ('t3', 's1', 'coder', 'Fetch web info', 'desc', 'failed', 'ModuleNotFoundError: No module named ''requests''', ?, ?)
        """, (now, now))

    # 4. Trigger prompt drift via mock tracker
    mock_router.tracker._calls[("phi4-mini:latest", "classification")] = 10
    mock_router.tracker._errors[("phi4-mini:latest", "classification")] = 3
    mock_router.tracker._latencies[("phi4-mini:latest", "classification")] = [16000.0] * 10

    # Patch server lifespan context
    from contextlib import asynccontextmanager
    @asynccontextmanager
    async def mock_lifespan(app_inst):
        yield
    orig_lifespan = app.router.lifespan_context
    app.router.lifespan_context = mock_lifespan

    # Wire server globals
    orig_db = getattr(app.state, "db_pool", None)
    orig_mgr = getattr(app.state, "memory_manager", None)
    orig_evo = getattr(app.state, "evolution_engine", None)

    app.state.db_pool = pool
    app.state.memory_manager = memory_mgr
    app.state.evolution_engine = engine

    yield pool, memory_mgr, prompt_reg, engine, mock_runtime, mock_router, tmp_path

    # Restore
    app.router.lifespan_context = orig_lifespan
    app.state.db_pool = orig_db
    app.state.memory_manager = orig_mgr
    app.state.evolution_engine = orig_evo

    await engine.stop()
    await prompt_reg.stop()
    await memory_mgr.stop()
    await pool.stop()


@pytest.mark.asyncio
async def test_detectors_and_scan(evolution_test_env):
    pool, memory_mgr, prompt_reg, engine, _, mock_router, tmp_path = evolution_test_env

    # Execute Scan
    proposals = await engine.run_scan()
    assert len(proposals) > 0

    # Ensure all types of proposals are generated
    types = [p.metadata["type"] for p in proposals]
    assert "repeated_failure" in types
    assert "semantic_overlap" in types
    assert "prompt_drift" in types
    assert "missing_package" in types

    # Check proposals are stored in DB
    db_proposals = await engine.get_proposals()
    assert len(db_proposals) == len(proposals)


@pytest.mark.asyncio
async def test_review_gate_actions(evolution_test_env):
    pool, memory_mgr, prompt_reg, engine, mock_runtime, _, _ = evolution_test_env

    # Run scan to create proposals
    proposals = await engine.run_scan()
    
    # 1. Test Semantic Overlap Consolidation
    overlap_prop = next(p for p in proposals if p.metadata["type"] == "semantic_overlap")
    m1_id = overlap_prop.metadata["memory_id_1"]
    m2_id = overlap_prop.metadata["memory_id_2"]
    
    success = await engine.approve(overlap_prop.id)
    assert success is True

    # Assert old memories are deleted and new one is stored
    with pool.get_read_connection() as conn:
        m1_row = conn.execute("SELECT id FROM memories WHERE id = ?", (m1_id,)).fetchone()
        m2_row = conn.execute("SELECT id FROM memories WHERE id = ?", (m2_id,)).fetchone()
        cons_row = conn.execute("SELECT content FROM memories WHERE category = 'consolidated_overlap'").fetchone()

    assert m1_row is None
    assert m2_row is None
    assert cons_row is not None
    assert cons_row["content"] == "Consolidated memory details."

    # 2. Test Prompt Update approval
    drift_prop = next(p for p in proposals if p.metadata["type"] == "prompt_drift")
    success = await engine.approve(drift_prop.id)
    assert success is True

    # Assert new prompt registered
    assert prompt_reg._cache["classification"] is not None
    active_ver = prompt_reg._active_cache["classification"]
    assert "evo_" in active_ver
    assert prompt_reg._cache["classification"][active_ver].template == "Optimized template prompt instruction."

    # 3. Test Repeated Failure (spawns agent session)
    fail_prop = next(p for p in proposals if p.metadata["type"] == "repeated_failure")
    success = await engine.approve(fail_prop.id)
    assert success is True
    assert mock_runtime.start_session.called is True


def test_evolution_api_endpoints(evolution_test_env):
    pool, memory_mgr, prompt_reg, engine, _, _, _ = evolution_test_env

    with TestClient(app) as client:
        # 1. Trigger scan
        response = client.post("/api/evolution/scan")
        assert response.status_code == 200
        
        # 2. List proposals
        response = client.get("/api/evolution/proposals")
        assert response.status_code == 200
        proposals = response.json()
        assert len(proposals) >= 0

        # Create a mock proposal to test approve/reject endpoint
        pid = "MOCK_TEST_PROP"
        with pool.get_write_connection() as conn:
            conn.execute("""
                INSERT INTO evolution_proposals (id, problem, evidence, possible_solutions, recommended_solution, affected_files, benefits, risks, implementation_plan, status, created_at, metadata)
                VALUES (?, 'prob', 'ev', '[]', 'rec', '[]', 'ben', 'risk', 'plan', 'pending', 'now', '{"type": "semantic_overlap", "memory_id_1": "1", "memory_id_2": "2", "consolidated_content": "xyz"}')
            """, (pid,))

        # Reject proposal
        response = client.post(f"/api/evolution/proposals/{pid}/reject")
        assert response.status_code == 200
        assert response.json()["status"] == "rejected"
