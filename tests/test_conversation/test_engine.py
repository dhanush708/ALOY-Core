import pytest
import pytest_asyncio
import json
from unittest.mock import AsyncMock, patch

from database.connection import DatabaseConnectionPool
from database.migrator import Migrator
from memory.manager import MemoryManager
from conversation.engine import ConversationEngine

@pytest_asyncio.fixture
async def conv_engine(tmp_path):
    db_path = str(tmp_path / "test_conv.db")
    pool = DatabaseConnectionPool(db_path)
    
    migrator = Migrator(pool, migrations_pkg="database.migrations")
    await migrator.migrate()
    
    mem_mgr = MemoryManager(pool)
    await mem_mgr.start()
    
    # Mock embedding generation so we don't need ollama
    mem_mgr.embeddings.generate = AsyncMock(return_value=[0.1]*768)
    
    engine = ConversationEngine(pool, mem_mgr)
    
    # Mock Intent classifier
    engine.pipeline[0]._classify = AsyncMock(return_value="simple_chat")
    
    # Mock Response generator
    async def fake_stream():
        yield "Hello"
        yield " world"
    engine.pipeline[4].process = AsyncMock()
    async def mock_process(ctx):
        ctx.response_stream = fake_stream()
        ctx.final_response = "Hello world"
        return ctx
    engine.pipeline[4].process.side_effect = mock_process
    
    return engine

@pytest.mark.asyncio
async def test_engine_flow(conv_engine):
    # 1. Start a conversation
    ctx = await conv_engine.process_message("test_conv_1", "Hi ALOY")
    
    assert ctx.intent == "simple_chat"
    assert ctx.state.id == "test_conv_1"
    assert ctx.state.turn_count == 1
    
    # History should contain the user message
    history = await conv_engine.history_store.get_history("test_conv_1")
    assert len(history) == 1
    assert history[0].role == "user"
    assert history[0].content == "Hi ALOY"
    
    # 2. Simulate streaming done
    await conv_engine.save_assistant_response("test_conv_1", "Hello world")
    
    # 3. Next turn
    ctx2 = await conv_engine.process_message("test_conv_1", "How are you?")
    assert ctx2.state.turn_count == 2
    
    # Verify history is loaded in context
    assert len(ctx2.history) == 3  # T1 user, T1 assistant, T2 user
    assert ctx2.history[0].role == "user"
    assert ctx2.history[1].role == "assistant"
    assert ctx2.history[2].role == "user"
