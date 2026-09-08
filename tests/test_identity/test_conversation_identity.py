import pytest
import pytest_asyncio
import json
from database.connection import DatabaseConnectionPool
from database.migrator import Migrator
from memory.manager import MemoryManager
from identity.engine import IdentityEngine
from conversation.engine import ConversationEngine
from conversation.pipeline import ConversationContext
from conversation.state import ConversationState
from conversation.streaming import sse_stream_handler

@pytest_asyncio.fixture
async def setup_engine(tmp_path):
    db_path = str(tmp_path / "test_conv_identity.db")
    pool = DatabaseConnectionPool(db_path)
    
    migrator = Migrator(pool, migrations_pkg="database.migrations")
    await migrator.migrate()
    
    manager = MemoryManager(pool)
    await manager.start()
    
    # Mock embedding generator
    from unittest.mock import AsyncMock, MagicMock
    manager.embeddings.generate = AsyncMock(return_value=[0.1] * 768)
    
    identity = IdentityEngine(pool, manager)
    await identity.initialize_if_needed()
    
    # Mock model router
    model_router = AsyncMock()
    model_router.resolve_model = MagicMock(return_value="mock_model")
    
    # Normal function returning async generator for stream
    def mock_stream_fn(*args, **kwargs):
        async def mock_generator():
            yield "Assistant: "
            yield "Hi Dhanush. "
            yield "<identity>Secret</identity>"
            yield "Let's "
            yield "code."
        return mock_generator()
        
    model_router.stream = mock_stream_fn
    model_router.stream_chat = mock_stream_fn
    
    engine = ConversationEngine(pool, manager, model_router=model_router, identity_engine=identity)
    return pool, manager, identity, model_router, engine

@pytest.mark.asyncio
async def test_pipeline_integration(setup_engine):
    pool, manager, identity, model_router, engine = setup_engine
    
    # Run a turn
    conv_id = "test_conversation"
    context = await engine.process_message(conv_id, "Write a fastapi route")
    
    # Verify ContextBuildStage populated full_prompt using IdentityEngine
    assert context.full_prompt is not None
    assert "You are ALOY" in context.full_prompt
    assert "ALOY Identity Profile" in context.full_prompt  # Public release: creator section
    assert "User Profile" in context.full_prompt            # Public release: user section
    
    # Test streaming and leakage stripping
    sse_generator = sse_stream_handler(context, engine, conv_id)
    emitted_tokens = []
    async for event in sse_generator:
        if event.startswith("data: "):
            payload = json.loads(event[6:].strip())
            if payload["type"] == "token":
                emitted_tokens.append(payload["content"])
                
    full_output = "".join(emitted_tokens)
    # Check that "Assistant:" header was stripped
    assert "Assistant:" not in full_output
    # Check that XML identity tag and "Secret" were stripped
    assert "Secret" not in full_output
    assert "<identity>" not in full_output
    # Check that clean output is emitted
    assert "Hi Dhanush. Let's code." in full_output
    
    # Verify the cleaned assistant response is saved to history without prompt leakage
    history = await engine.history_store.get_history(conv_id)
    assistant_msgs = [m for m in history if m.role == "assistant"]
    assert len(assistant_msgs) == 1
    assert "Hi Dhanush. Let's code." in assistant_msgs[0].content
    assert "Secret" not in assistant_msgs[0].content
