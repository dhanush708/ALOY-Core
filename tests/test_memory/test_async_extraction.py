import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, ANY

from conversation.engine import ConversationEngine
from memory.manager import MemoryManager
from models.router import ModelRouter

@pytest.fixture
def mock_db_pool():
    pool = MagicMock()
    conn = MagicMock()
    conn.__enter__.return_value = conn
    pool.get_write_connection.return_value = conn
    return pool

@pytest.fixture
def mock_memory_manager():
    manager = AsyncMock(spec=MemoryManager)
    return manager

@pytest.fixture
def mock_model_router():
    router = AsyncMock(spec=ModelRouter)
    return router

@pytest.fixture
def engine(mock_db_pool, mock_memory_manager, mock_model_router):
    eng = ConversationEngine(
        db_pool=mock_db_pool,
        memory_manager=mock_memory_manager,
        model_router=mock_model_router
    )
    eng.history_store = AsyncMock()
    return eng


@pytest.mark.asyncio
async def test_short_conversation_extraction(engine, mock_model_router):
    mock_msg = MagicMock()
    mock_msg.role = "user"
    mock_msg.content = "My dream company is OpenAI"
    
    engine.history_store.get_history.return_value = [mock_msg]
    
    mock_model_router.generate.side_effect = [
        "YES",
        "The user's dream company is OpenAI"
    ]
    
    engine._merge_or_store_fact = AsyncMock()
    
    await engine._async_memory_evaluation("test_conv_1")
    
    mock_model_router.generate.assert_any_call(
        task="classification",
        prompt=ANY,
        options={"temperature": 0.0}
    )
    
    mock_model_router.generate.assert_any_call(
        "reflection",
        ANY
    )
    
    engine._merge_or_store_fact.assert_called_once_with("test_conv_1", "The user's dream company is OpenAI")


@pytest.mark.asyncio
async def test_noise_rejection(engine, mock_model_router):
    mock_msg = MagicMock()
    mock_msg.role = "user"
    mock_msg.content = "Hello, how are you today?"
    
    engine.history_store.get_history.return_value = [mock_msg]
    
    mock_model_router.generate.return_value = "NO"
    
    engine._async_extract_and_store = AsyncMock()
    
    await engine._async_memory_evaluation("test_conv_2")
    
    mock_model_router.generate.assert_not_called()
    engine._async_extract_and_store.assert_not_called()
