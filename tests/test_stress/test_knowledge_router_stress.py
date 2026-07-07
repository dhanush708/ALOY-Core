import pytest
import pytest_asyncio
import json
import asyncio
from unittest.mock import AsyncMock, MagicMock
from database.connection import DatabaseConnectionPool
from database.migrator import Migrator
from memory.manager import MemoryManager
from knowledge.doc_intelligence import DocumentationIntelligence
from knowledge.router import KnowledgeRouter

@pytest_asyncio.fixture
async def knowledge_stress_env(tmp_path):
    db_path = str(tmp_path / "test_knowledge_stress.db")
    pool = DatabaseConnectionPool(db_path)
    await pool.start()
    
    migrator = Migrator(pool, migrations_pkg="database.migrations")
    await migrator.migrate()
    
    memory_mgr = MemoryManager(pool)
    await memory_mgr.start()
    
    # Mock embedding generator
    memory_mgr.embeddings.generate = AsyncMock(return_value=[0.1] * 768)
    
    mock_router = MagicMock()
    mock_router.generate = AsyncMock(return_value=json.dumps({
        "answer": "Mocked verified answer.",
        "confidence_score": 0.95,
        "source_quality": "high",
        "lessons_learned": "Mocked lessons learned."
    }))
    
    doc_intel = DocumentationIntelligence(pool, memory_mgr, mock_router)
    router_engine = KnowledgeRouter(pool, memory_mgr, doc_intel, mock_router)
    
    # Mock web search tool with correct URL/Snippet structure
    mock_search = AsyncMock(return_value="Title: Test Page\nURL: https://test.com\nSnippet: Search details.\n---")
    router_engine.search_tool.execute = mock_search
    
    yield pool, memory_mgr, router_engine, mock_router
    
    await memory_mgr.stop()
    await pool.stop()

@pytest.mark.asyncio
async def test_offline_mode_graceful_fallback(knowledge_stress_env):
    pool, memory_mgr, router_engine, mock_router = knowledge_stress_env
    
    # Simulate search tool failure (representing offline/disconnected internet)
    router_engine.search_tool.execute.side_effect = RuntimeError("No internet connection")
    
    # Seed a local memory that has information
    await memory_mgr.store(
        type="semantic",
        content="Local fallback matches: FastAPI lifespan is configured inside app initialization.",
        tier="permanent",
        importance=0.9
    )
    # Give DB FTS triggers a moment to index
    await asyncio.sleep(0.1)
    
    # Query something that would normally escalate to web search but fails and should fallback to memory FTS
    res = await router_engine.query_escalation("FastAPI lifespan")
    # It should fall back to global memory layer instead of throwing internet connection errors
    assert res["layer"] == "global_memory"
    assert "FastAPI lifespan is configured" in res["answer"]

@pytest.mark.asyncio
async def test_confidence_scoring_under_conflicting_sources(knowledge_stress_env):
    pool, memory_mgr, router_engine, mock_router = knowledge_stress_env
    
    # We simulate a low confidence score response from LLM source verifier
    mock_router.generate.return_value = json.dumps({
        "answer": "Conflicting source details.",
        "confidence_score": 0.35, # Low confidence
        "source_quality": "low",
        "lessons_learned": "Sources disagree on details."
    })
    
    # Query should run
    res = await router_engine.query_escalation("complex conflicting engineering standard")
    # Low confidence should still return, but with layer information and marked confidence (keyed as "confidence" in routing dictionary)
    assert res["confidence"] == 0.35
    assert "Conflicting" in res["answer"]
