import pytest
import pytest_asyncio
import asyncio
import json
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from fastapi.testclient import TestClient

# Globally patch EmbeddingEngine before any test setup or lifespan runs
from unittest.mock import AsyncMock
import memory.embeddings
memory.embeddings.EmbeddingEngine.generate = AsyncMock(return_value=[0.1] * 768)
memory.embeddings.EmbeddingEngine.generate_batch = AsyncMock(return_value=[[0.1] * 768])

from api.server import app
from database.connection import DatabaseConnectionPool
from database.migrator import Migrator
from memory.manager import MemoryManager
from knowledge.doc_intelligence import DocumentationIntelligence
from knowledge.router import KnowledgeRouter

@pytest_asyncio.fixture
async def router_test_env(tmp_path):
    db_path = str(tmp_path / "test_router.db")
    pool = DatabaseConnectionPool(db_path)
    await pool.start()
    
    migrator = Migrator(pool, migrations_pkg="database.migrations")
    await migrator.migrate()
    
    memory_mgr = MemoryManager(pool)
    await memory_mgr.start()
    
    # Mock ModelRouter
    mock_router = MagicMock()
    mock_router.generate = AsyncMock(return_value=json.dumps({
        "answer": "Mocked verified answer.",
        "confidence_score": 0.95,
        "source_quality": "high",
        "lessons_learned": "Mocked lessons learned."
    }))
    
    doc_intel = DocumentationIntelligence(pool, memory_mgr, mock_router)
    router_engine = KnowledgeRouter(pool, memory_mgr, doc_intel, mock_router)
    
    # Mock web search tool inside router
    mock_search = AsyncMock(return_value="Title: Test Page\nURL: https://test.com\nSnippet: This contains relevant quickstart details.\n---")
    router_engine.search_tool.execute = mock_search
    
    # Wire app state
    orig_db = getattr(app.state, "db_pool", None)
    orig_mgr = getattr(app.state, "memory_manager", None)
    orig_intel = getattr(app.state, "doc_intelligence", None)
    orig_router = getattr(app.state, "knowledge_router", None)
    
    # Patch lifespan context
    from contextlib import asynccontextmanager
    @asynccontextmanager
    async def mock_lifespan(app_inst):
        yield
    orig_lifespan = app.router.lifespan_context
    app.router.lifespan_context = mock_lifespan
    
    app.state.db_pool = pool
    app.state.memory_manager = memory_mgr
    app.state.doc_intelligence = doc_intel
    app.state.knowledge_router = router_engine
    
    yield pool, memory_mgr, router_engine, mock_router, tmp_path
    
    # Restore and stop
    app.router.lifespan_context = orig_lifespan
    app.state.db_pool = orig_db
    app.state.memory_manager = orig_mgr
    app.state.doc_intelligence = orig_intel
    app.state.knowledge_router = orig_router
    
    await memory_mgr.stop()
    await pool.stop()

@pytest.mark.asyncio
async def test_escalation_flow_layer1(router_test_env):
    pool, memory_mgr, router_engine, _, tmp_path = router_test_env
    
    # Seed high-confidence memory for Layer 1
    m = await memory_mgr.store(
        type="semantic",
        content="Layer 1 match found: FastAPI lifespan configuration guides.",
        tier="permanent",
        importance=0.95
    )
    # RRF scoring relies on matching embeddings, which we mocked, so this will score 1.0
    await asyncio.sleep(0.2)
    
    res = await router_engine.query_escalation("lifespan configuration")
    assert res["layer"] == "global_memory"
    assert "FastAPI lifespan" in res["answer"]

@pytest.mark.asyncio
async def test_escalation_flow_layer4_and_5(router_test_env):
    pool, memory_mgr, router_engine, mock_router, tmp_path = router_test_env
    
    async def mock_generate(task, prompt):
        if "Official Snippets" in prompt:
            return json.dumps({
                "summary": "Official docs: requests.get starts a connection.",
                "examples": "```python\nrequests.get(...)\n```"
            })
        return json.dumps({
            "answer": "Mocked verified answer.",
            "confidence_score": 0.95,
            "source_quality": "high",
            "lessons_learned": "Mocked lessons learned."
        })
    mock_router.generate.side_effect = mock_generate
    
    # 1. Seed official doc for layer 4
    m = await memory_mgr.store(
        type="documentation",
        content="Official docs: requests.get starts a connection.",
        tier="permanent",
        is_protected=True,
        metadata={"package": "requests", "version": "2.31.0", "doc_type": "api_reference"}
    )
    memory_mgr.tags.add_tags(m.id, ["doc:offline", "package:requests", "version:2.31.0", "doc_type:api_reference"])
    await asyncio.sleep(0.2)
    
    res = await router_engine.query_escalation("requests.get starts connection", package="requests")
    assert res["layer"] == "official_documentation"
    assert "requests.get" in res["answer"]

    # 2. Trigger web search (Layer 5) when query doesn't match local docs
    res_web = await router_engine.query_escalation("what is the latest weather in Mars")
    assert res_web["layer"] == "internet_search"
    assert res_web["answer"] == "Mocked verified answer."
    
    # Assert temporary memory was saved
    with pool.get_read_connection() as conn:
        rows = conn.execute("SELECT id, content FROM memories WHERE tier = 'temporary'").fetchall()
    assert len(rows) == 1
    assert "Mars" in rows[0]["content"]

@pytest.mark.asyncio
async def test_consolidation(router_test_env):
    pool, memory_mgr, router_engine, mock_router, _ = router_test_env
    
    # Seed temporary research memory
    m = await memory_mgr.store(
        type="research_findings",
        content="Temporary findings on requests package behavior.",
        tier="temporary",
        is_protected=True,
        metadata={"query": "requests usage"}
    )
    memory_mgr.tags.add_tags(m.id, ["research", "temporary"])
    
    # Mock LLM consolidation output
    mock_router.generate.return_value = "Consolidated Long-Term Insight: Requests requires clean connections."
    
    count = await router_engine.consolidate_research()
    assert count == 1
    
    # Assert temporary is deleted and long term is created
    with pool.get_read_connection() as conn:
        temp_rows = conn.execute("SELECT id FROM memories WHERE tier = 'temporary'").fetchall()
        long_rows = conn.execute("SELECT id, content FROM memories WHERE tier = 'long_term'").fetchall()
        
    assert len(temp_rows) == 0
    assert len(long_rows) == 1
    assert "Requests requires clean connections" in long_rows[0]["content"]

def test_router_api_routes(router_test_env):
    pool, memory_mgr, router_engine, _, tmp_path = router_test_env
    
    with TestClient(app) as client:
        # Seed cache
        router_engine.cache.set("mars query", {"answer": "Mars weather info", "layer": "cache"})
        
        # 1. Test GET /api/knowledge/cache/stats
        response = client.get("/api/knowledge/cache/stats")
        assert response.status_code == 200
        assert response.json()["cache_size"] == 1
        
        # 2. Test GET /api/knowledge/query (hits cache)
        response = client.get("/api/knowledge/query?query=mars query")
        assert response.status_code == 200
        data = response.json()
        assert data["answer"] == "Mars weather info"
        assert data["layer"] == "cache"
