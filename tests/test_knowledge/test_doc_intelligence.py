import pytest
import pytest_asyncio
import asyncio
import json
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
from knowledge.dependency_resolver import DependencyResolver
from knowledge.indexer import OfflineDocIndexer
from knowledge.cache import DocCache
from knowledge.doc_intelligence import DocumentationIntelligence

@pytest_asyncio.fixture
async def knowledge_test_env(tmp_path):
    db_path = str(tmp_path / "test_knowledge.db")
    pool = DatabaseConnectionPool(db_path)
    await pool.start()
    
    migrator = Migrator(pool, migrations_pkg="database.migrations")
    await migrator.migrate()
    
    memory_mgr = MemoryManager(pool)
    await memory_mgr.start()
    
    # Mock ModelRouter
    mock_router = MagicMock()
    mock_router.generate = AsyncMock(return_value=json.dumps({
        "summary": "Mocked summary for query.",
        "examples": "```python\n# Mocked code example\n```"
    }))
    
    doc_intel = DocumentationIntelligence(pool, memory_mgr, mock_router)
    
    # Wire app state
    orig_db = getattr(app.state, "db_pool", None)
    orig_mgr = getattr(app.state, "memory_manager", None)
    orig_intel = getattr(app.state, "doc_intelligence", None)
    
    # Save original lifespan and patch it
    from contextlib import asynccontextmanager
    @asynccontextmanager
    async def mock_lifespan(app_inst):
        yield
    orig_lifespan = app.router.lifespan_context
    app.router.lifespan_context = mock_lifespan
    
    app.state.db_pool = pool
    app.state.memory_manager = memory_mgr
    app.state.doc_intelligence = doc_intel
    
    yield pool, memory_mgr, doc_intel, mock_router, tmp_path
    
    # Restore and stop
    app.router.lifespan_context = orig_lifespan
    app.state.db_pool = orig_db
    app.state.memory_manager = orig_mgr
    app.state.doc_intelligence = orig_intel
    
    await memory_mgr.stop()
    await pool.stop()

def test_dependency_resolver(tmp_path):
    resolver = DependencyResolver()
    
    # Write requirements.txt
    req_file = tmp_path / "requirements.txt"
    req_file.write_text("fastapi==0.110.1\nhttpx>=0.25.0\n# comment\npydantic\n")
    
    # Write package.json
    pkg_file = tmp_path / "package.json"
    pkg_file.write_text(json.dumps({
        "dependencies": {
            "express": "^4.18.2"
        },
        "devDependencies": {
            "jest": "~29.0.0"
        }
    }))
    
    # Write pyproject.toml
    toml_file = tmp_path / "pyproject.toml"
    toml_file.write_text("""
[tool.poetry.dependencies]
python = "^3.11"
requests = "2.31.0"
[tool.poetry.group.dev.dependencies]
black = "^23.0"
""")
    
    versions = resolver.resolve_versions(tmp_path)
    
    assert versions["fastapi"] == "0.110.1"
    assert versions["httpx"] == "0.25.0"
    assert versions["pydantic"] == "unknown"
    assert versions["express"] == "4.18.2"
    assert versions["jest"] == "29.0.0"
    assert versions["requests"] == "2.31.0"

@pytest.mark.asyncio
async def test_offline_doc_indexing(knowledge_test_env):
    pool, memory_mgr, doc_intel, _, tmp_path = knowledge_test_env
    
    # Create doc files
    doc_dir = tmp_path / "docs"
    doc_dir.mkdir()
    
    md_file = doc_dir / "asyncio.md"
    md_file.write_text("""
# Asyncio Reference
This is the core asyncio guide.

## Concurrency Basics
Asyncio allows cooperative multitasking.
""")
    
    html_file = doc_dir / "index.html"
    html_file.write_text("<html><body><h1>FastAPI docs</h1><p>Welcome to FastAPI reference.</p></body></html>")
    
    indexed_count = await doc_intel.indexer.index_directory(doc_dir, "fastapi", "0.110.1")
    assert indexed_count >= 2
    
    # Check DB
    with pool.get_read_connection() as conn:
        rows = conn.execute("SELECT * FROM memories WHERE type = 'documentation'").fetchall()
    
    assert len(rows) >= 2
    for r in rows:
        assert r["is_protected"] == 1
        meta = json.loads(r["metadata"])
        assert meta["package"] == "fastapi"
        assert meta["version"] == "0.110.1"

@pytest.mark.asyncio
async def test_version_aware_selection_and_search(knowledge_test_env):
    pool, memory_mgr, doc_intel, _, tmp_path = knowledge_test_env
    
    # Seed memories of different versions
    m1 = await memory_mgr.store(
        type="documentation",
        content="FastAPI 0.110 lifecycle docs: Use lifespan async context manager.",
        tier="permanent",
        is_protected=True,
        metadata={"package": "fastapi", "version": "0.110.1", "doc_type": "api_reference"}
    )
    memory_mgr.tags.add_tags(m1.id, ["doc:offline", "package:fastapi", "version:0.110.1", "doc_type:api_reference"])
    
    m2 = await memory_mgr.store(
        type="documentation",
        content="FastAPI 0.90 startup docs: Use @app.on_event('startup').",
        tier="permanent",
        is_protected=True,
        metadata={"package": "fastapi", "version": "0.90.0", "doc_type": "api_reference"}
    )
    memory_mgr.tags.add_tags(m2.id, ["doc:offline", "package:fastapi", "version:0.90.0", "doc_type:api_reference"])
    
    # Write workspace manifest resolving to v0.90.0
    req_file = tmp_path / "requirements.txt"
    req_file.write_text("fastapi==0.90.0")
    
    # Wait for background embedding tasks to complete
    await asyncio.sleep(0.2)
    
    # Search documentation
    results = await doc_intel.search_docs(
        query="startup lifecycle lifespan",
        package="fastapi",
        workspace_path=tmp_path,
        limit=2
    )
    
    assert len(results) == 2
    # First result should be the one matching 0.90.0 due to version scoring multiplier
    assert results[0]["version"] == "0.90.0"

@pytest.mark.asyncio
async def test_summarization_and_cache(knowledge_test_env):
    pool, memory_mgr, doc_intel, mock_router, tmp_path = knowledge_test_env
    
    # Seed documentation memory
    m = await memory_mgr.store(
        type="documentation",
        content="FastAPI lifespan lifecycle management content.",
        tier="permanent",
        is_protected=True,
        metadata={"package": "fastapi", "version": "0.110.1", "doc_type": "api_reference"}
    )
    memory_mgr.tags.add_tags(m.id, ["doc:offline", "package:fastapi", "version:0.110.1", "doc_type:api_reference"])
    
    # Wait for background embedding task to complete
    await asyncio.sleep(0.2)
    
    query = "How to manage lifespan in fastapi?"
    
    # 1. First call (cache miss)
    result = await doc_intel.get_summary_and_examples(query, "fastapi")
    assert result["summary"] == "Mocked summary for query."
    assert "Mocked code example" in result["examples"]
    assert mock_router.generate.call_count == 1
    
    # 2. Second call (cache hit)
    result2 = await doc_intel.get_summary_and_examples(query, "fastapi")
    assert result2["summary"] == "Mocked summary for query."
    assert mock_router.generate.call_count == 1

def test_api_routes(knowledge_test_env):
    pool, memory_mgr, doc_intel, _, tmp_path = knowledge_test_env
    
    # Run in TestClient lifespan
    with TestClient(app) as client:
        # 1. Test POST /api/docs/index
        doc_dir = tmp_path / "docs"
        doc_dir.mkdir(exist_ok=True)
        doc_file = doc_dir / "quickstart.md"
        doc_file.write_text("# Quickstart\nGetting started.")
        
        index_payload = {
            "dir_path": str(doc_dir),
            "package": "requests",
            "version": "2.31.0",
            "doc_type": "api_reference"
        }
        
        response = client.post("/api/docs/index", json=index_payload)
        assert response.status_code == 200
        assert response.json()["indexed_chunks"] == 1
        
        # Wait for background embedding tasks to complete
        import time
        time.sleep(0.2)
        
        # 2. Test GET /api/docs/packages
        response = client.get("/api/docs/packages")
        assert response.status_code == 200
        packages = response.json()
        assert len(packages) == 1
        assert packages[0]["package"] == "requests"
        assert packages[0]["version"] == "2.31.0"
        
        # 3. Test GET /api/docs/search
        response = client.get("/api/docs/search?query=quickstart&package=requests")
        assert response.status_code == 200
        results = response.json()
        assert len(results) == 1
        assert "Quickstart" in results[0]["content"]
        
        # 4. Test GET /api/docs/summarize
        response = client.get("/api/docs/summarize?query=quickstart&package=requests")
        assert response.status_code == 200
        summary = response.json()
        assert "summary" in summary
        assert "sources" in summary
