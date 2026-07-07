import pytest
import pytest_asyncio
import asyncio
from unittest.mock import patch, AsyncMock
import httpx

from memory.embeddings import EmbeddingEngine
from database.connection import DatabaseConnectionPool
from database.migrator import Migrator
from memory.vector_store import VectorStore

@pytest_asyncio.fixture
async def vector_store(tmp_path):
    db_path = str(tmp_path / "test_vec.db")
    pool = DatabaseConnectionPool(db_path)
    
    migrator = Migrator(pool, migrations_pkg="database.migrations")
    await migrator.migrate()
    
    return pool, VectorStore(pool)

@pytest.mark.asyncio
async def test_embedding_engine():
    engine = EmbeddingEngine()
    
    from unittest.mock import MagicMock
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"embeddings": [[0.1] * 768]}
    
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response
        emb = await engine.generate("test text")
        
    assert emb is not None
    assert len(emb) == 768
    assert emb[0] == 0.1

@pytest.mark.asyncio
async def test_vector_store(vector_store):
    pool, store = vector_store
    
    # We must insert a dummy memory row first to satisfy any rowid relations, 
    # though in sqlite-vec we linked by rowid, which doesn't strictly enforce FK on rowid itself.
    with pool.get_write_connection() as conn:
        conn.execute("INSERT INTO memories (id, type, content, updated_at, created_at) VALUES ('m1', 'test', 'text', 'now', 'now')")
        cursor = conn.execute("SELECT rowid FROM memories WHERE id = 'm1'")
        rowid1 = cursor.fetchone()["rowid"]
        
        conn.execute("INSERT INTO memories (id, type, content, updated_at, created_at) VALUES ('m2', 'test', 'text2', 'now', 'now')")
        cursor = conn.execute("SELECT rowid FROM memories WHERE id = 'm2'")
        rowid2 = cursor.fetchone()["rowid"]

    emb1 = [0.1] * 768
    emb2 = [0.9] * 768
    
    await store.upsert_embedding(rowid1, emb1)
    await store.upsert_embedding(rowid2, emb2)
    
    # Search for something close to emb1
    query_emb = [0.11] * 768
    results = await store.search(query_emb, limit=2)
    
    assert len(results) == 2
    # The first result should be rowid1 because it is closer
    assert results[0][0] == rowid1
    assert results[1][0] == rowid2
