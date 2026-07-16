import pytest
import pytest_asyncio
import asyncio
import threading
from unittest.mock import AsyncMock, MagicMock
from database.connection import DatabaseConnectionPool
from database.migrator import Migrator
from memory.manager import MemoryManager
from conversation.context_intelligence import ContextIntelligenceEngine, ContextPack
from conversation.state import ConversationState
from conversation.history import ConversationMessage
from models.router import ModelRouter, Priority

@pytest_asyncio.fixture
async def db_pool(tmp_path):
    db_path = str(tmp_path / "test_perf.db")
    pool = DatabaseConnectionPool(db_path, max_read_connections=3)
    
    # Run migrations
    migrator = Migrator(pool, migrations_pkg="database.migrations")
    await migrator.migrate()
    
    yield pool
    await pool.stop()

@pytest_asyncio.fixture
async def memory_manager(db_pool):
    manager = MemoryManager(db_pool)
    await manager.start()
    
    # Mock embedding generation
    manager.embeddings.generate = AsyncMock(return_value=[0.1] * 768)
    return manager

@pytest.mark.asyncio
async def test_database_connection_pooling(db_pool):
    # Test read connection sharing/reuse
    conns = []
    
    # Acquire 3 connections (our max_read_connections limit)
    with db_pool.get_read_connection() as c1:
        conns.append(c1)
        with db_pool.get_read_connection() as c2:
            conns.append(c2)
            with db_pool.get_read_connection() as c3:
                conns.append(c3)
                
                # Verify we got distinct connection objects
                assert len(set(id(c) for c in conns)) == 3
                
    # Verify reusing read connection from pool
    with db_pool.get_read_connection() as c4:
        # It should be one of the connections we just released
        assert id(c4) in [id(c) for c in conns]

    # Test serialized writer connection
    write_conns = []
    def do_write():
        with db_pool.get_write_connection() as conn:
            write_conns.append(conn)
            
    # Run in multiple threads to ensure serialization lock works
    t1 = threading.Thread(target=do_write)
    t2 = threading.Thread(target=do_write)
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    
    assert len(write_conns) == 2
    # Both should be the same connection object because of the serialized self._write_conn
    assert id(write_conns[0]) == id(write_conns[1])

@pytest.mark.asyncio
async def test_context_intelligence_caching():
    engine = ContextIntelligenceEngine()
    
    # Verify cache starts empty
    assert len(engine._context_cache) == 0
    
    state = ConversationState(id="session_1")
    history = [ConversationMessage(id="msg_1", conversation_id="session_1", role="user", content="Hello")]
    
    # Mock candidate memories
    from memory.types import Memory, ScoredMemory
    m1 = Memory(id="mem1", type="semantic", content="The sky is blue.", tier="short_term", importance=0.8)
    sm1 = ScoredMemory(memory=m1, score=0.9)
    
    # Build context pack (should miss cache)
    pack1 = engine.build_context(
        query="What color is the sky?",
        intent="simple_chat",
        conversation_state=state,
        system_prompt_template="You are a helper.",
        identity_text="ALOY",
        candidate_memories=[sm1],
        history=history,
        total_budget=4000
    )
    
    assert len(engine._context_cache) == 1
    
    # Build context again with exact same params (should hit cache)
    pack2 = engine.build_context(
        query="What color is the sky?",
        intent="simple_chat",
        conversation_state=state,
        system_prompt_template="You are a helper.",
        identity_text="ALOY",
        candidate_memories=[sm1],
        history=history,
        total_budget=4000
    )
    
    # Check that they refer to the exact same object (cache HIT)
    assert id(pack1) == id(pack2)
    
    # Now change one parameter (e.g. system prompt)
    pack3 = engine.build_context(
        query="What color is the sky?",
        intent="simple_chat",
        conversation_state=state,
        system_prompt_template="You are a friendly helper.",
        identity_text="ALOY",
        candidate_memories=[sm1],
        history=history,
        total_budget=4000
    )
    
    # Should miss cache and generate a new pack
    assert id(pack1) != id(pack3)
    assert len(engine._context_cache) == 2

@pytest.mark.asyncio
async def test_memory_retrieval_caching(memory_manager):
    # Store some memories
    mem1 = await memory_manager.store("episodic", "I had pizza for dinner.", category="food")
    mem2 = await memory_manager.store("episodic", "I had pasta for lunch.", category="food")
    
    # Search first time (cache MISS)
    assert len(memory_manager._retrieval_cache) == 0
    res1 = await memory_manager.retrieve("pizza", limit=5)
    assert len(res1) > 0
    assert len(memory_manager._retrieval_cache) == 1
    
    # Search second time (cache HIT)
    res2 = await memory_manager.retrieve("pizza", limit=5)
    assert len(res2) == len(res1)
    assert res2[0].memory.id == res1[0].memory.id
    
    # Now write/store a new memory (should invalidate retrieval cache)
    await memory_manager.store("semantic", "Apples are red.")
    assert len(memory_manager._retrieval_cache) == 0
    
    # Re-retrieve to fill cache
    await memory_manager.retrieve("pizza", limit=5)
    assert len(memory_manager._retrieval_cache) == 1
    
    # Update memory (should invalidate retrieval cache)
    await memory_manager.update(mem1.id, content="I had double cheese pizza for dinner.")
    assert len(memory_manager._retrieval_cache) == 0
    
    # Re-retrieve
    await memory_manager.retrieve("pizza", limit=5)
    assert len(memory_manager._retrieval_cache) == 1
    
    # Delete memory (should invalidate cache)
    await memory_manager.delete(mem2.id, force=True)
    assert len(memory_manager._retrieval_cache) == 0

@pytest.mark.asyncio
async def test_model_router_keep_alive():
    # Mock OllamaClient
    client_mock = MagicMock()
    client_mock.generate = AsyncMock(return_value="Mock response")
    
    router = ModelRouter()
    router.client = client_mock
    
    # Test background priority -> keep_alive should be "10s"
    await router.generate(
        task="memory_generation", # BACKGROUND priority
        prompt="Synthesize observations.",
    )
    
    # Verify keep_alive was passed as "10s"
    client_mock.generate.assert_called_with(
        "phi4-mini:latest", "Synthesize observations.", None, keep_alive="10s"
    )
    
    # Test conversation priority -> keep_alive should be "5m"
    await router.generate(
        task="simple_chat", # CONVERSATION priority
        prompt="Hi ALOY",
    )
    
    client_mock.generate.assert_called_with(
        "phi4-mini:latest", "Hi ALOY", None, keep_alive="5m"
    )

    # Test preloading
    client_mock.generate.reset_mock()
    success = await router.preload_model("qwen3:8b")
    assert success is True
    client_mock.generate.assert_called_with("qwen3:8b", "", keep_alive="5m")
