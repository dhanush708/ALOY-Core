import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from conversation.engine import ConversationEngine
from memory.manager import MemoryManager

@pytest.fixture
def mock_db_pool():
    pool = MagicMock()
    conn = MagicMock()
    conn.__enter__.return_value = conn
    pool.get_write_connection.return_value = conn
    return pool

@pytest.fixture
def engine(mock_db_pool):
    eng = ConversationEngine(
        db_pool=mock_db_pool,
        memory_manager=AsyncMock(spec=MemoryManager),
        model_router=AsyncMock()
    )
    eng.history_store = AsyncMock()
    return eng

@pytest.mark.asyncio
@patch('memory.vector_store.VectorStore')
@patch('memory.embeddings.EmbeddingEngine')
async def test_fact_update(MockEmbeddingEngine, MockVectorStore, engine, mock_db_pool):
    # Setup mocks
    mock_vec_store = MockVectorStore.return_value
    mock_emb_engine = MockEmbeddingEngine.return_value
    mock_emb_engine.generate = AsyncMock(return_value=[0.1, 0.2])
    
    # Simulate finding a highly similar existing fact
    mock_vec_store.search.return_value = [
        {"id": "existing-uuid", "score": 0.90, "content": "The user's dream company is OpenAI"}
    ]
    
    # Simulate LLM merging the facts (REMOVED)
    # The system should do a deterministic direct update without an LLM
    
    await engine._merge_or_store_fact("test_conv_3", "The user's dream company is Anthropic")
    
    # Verify the SQL update was called instead of inserting a new memory
    mock_db_pool.get_write_connection.assert_called()
    conn = mock_db_pool.get_write_connection.return_value.__enter__.return_value
    conn.execute.assert_called_with(
        "UPDATE memories SET content = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        ("The user's dream company is Anthropic", "existing-uuid")
    )
    
    # Verify new memory was NOT stored as a duplicate
    engine.memory_manager.store.assert_not_called()
    
    # Verify LLM was NOT invoked
    engine.model_router.generate.assert_not_called()
