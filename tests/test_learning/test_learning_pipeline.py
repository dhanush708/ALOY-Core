import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock

from learning.engine import LearningEngine
from learning.pipeline import LearningContext, LearningCandidate
from learning.stages.filter import LearningFilterStage
from learning.stages.extraction import ExtractionStage
from learning.stages.duplicate_detection import DuplicateDetectionStage
from learning.stages.contradiction_detection import ContradictionDetectionStage
from learning.stages.promotion import PromotionStage
from memory.types import Memory, ScoredMemory
from datetime import datetime, timezone

@pytest.fixture
def mock_model_router():
    router = MagicMock()
    router.is_busy.return_value = False
    
    # Mock LLM response
    json_resp = """
    {
      "observations": [{"content": "User prefers python", "confidence": 0.95}],
      "understandings": [{"content": "User is a backend dev", "confidence": 0.8}],
      "insights": []
    }
    """
    router.generate = AsyncMock(return_value=json_resp)
    return router

@pytest.fixture
def mock_memory_manager():
    manager = AsyncMock()
    
    # Empty retrieve initially to pass duplicate check
    manager.retrieve.return_value = []
    return manager

@pytest.fixture
def dummy_history():
    return [
        {"role": "user", "content": "I prefer python for backend work."},
        {"role": "assistant", "content": "Got it. Python is great for backend."}
    ]

@pytest.mark.asyncio
async def test_filter_stage_skip(dummy_history):
    stage = LearningFilterStage()
    
    # Too short
    ctx = LearningContext(conversation_id="conv1", history=[{"role": "user", "content": "hi"}])
    ctx = await stage.process(ctx)
    assert ctx.should_skip is True
    
    # Valid length
    ctx = LearningContext(conversation_id="conv2", history=dummy_history)
    ctx = await stage.process(ctx)
    assert ctx.should_skip is False

@pytest.mark.asyncio
async def test_extraction_stage(mock_model_router, dummy_history):
    stage = ExtractionStage(mock_model_router)
    ctx = LearningContext(conversation_id="conv1", history=dummy_history)
    
    ctx = await stage.process(ctx)
    assert ctx.extracted is True
    assert len(ctx.candidates) == 2
    assert ctx.candidates[0].content == "User prefers python"
    assert ctx.candidates[0].confidence == 0.95

@pytest.mark.asyncio
async def test_duplicate_detection(mock_memory_manager):
    stage = DuplicateDetectionStage(mock_memory_manager)
    
    # Create candidate
    candidate = LearningCandidate(content="User prefers python", type="observation", confidence=0.95)
    ctx = LearningContext(conversation_id="c1", history=[], candidates=[candidate])
    
    # Setup mock to return a duplicate (score > 0.95 and same type)
    m = Memory(id="1", type="observation", content="User prefers python", tier="working", importance=0.9, created_at=datetime.now(timezone.utc).isoformat(), updated_at=datetime.now(timezone.utc).isoformat())
    mock_memory_manager.retrieve.return_value = [ScoredMemory(memory=m, score=0.98, relevance_details={})]
    
    ctx = await stage.process(ctx)
    assert len(ctx.candidates) == 0  # Should be dropped as duplicate

@pytest.mark.asyncio
async def test_contradiction_detection(mock_memory_manager):
    stage = ContradictionDetectionStage(mock_memory_manager)
    
    # Setup candidate
    candidate = LearningCandidate(content="User prefers java", type="observation", confidence=0.8)
    ctx = LearningContext(conversation_id="c1", history=[], candidates=[candidate])
    
    # Setup mock to return a contradiction (score between 0.5 and 0.85 and same type)
    m = Memory(id="1", type="observation", content="User prefers python", tier="working", importance=0.9, created_at=datetime.now(timezone.utc).isoformat(), updated_at=datetime.now(timezone.utc).isoformat())
    mock_memory_manager.retrieve.return_value = [ScoredMemory(memory=m, score=0.6, relevance_details={})]
    
    ctx = await stage.process(ctx)
    assert len(ctx.candidates) == 1  # For now, contradiction stage just logs and keeps it, per our simplified implementation

@pytest.mark.asyncio
async def test_promotion_stage(mock_memory_manager):
    stage = PromotionStage(mock_memory_manager)
    
    candidate1 = LearningCandidate(content="High conf", type="observation", confidence=0.95) # Should be permanent
    candidate2 = LearningCandidate(content="Med conf", type="understanding", confidence=0.6) # Should be short_term
    
    ctx = LearningContext(conversation_id="c1", history=[], candidates=[candidate1, candidate2])
    ctx = await stage.process(ctx)
    
    assert mock_memory_manager.store.call_count == 2
    
    # Check calls
    calls = mock_memory_manager.store.call_args_list
    assert calls[0].kwargs['tier'] == 'permanent'
    assert calls[1].kwargs['tier'] == 'short_term'

@pytest.mark.asyncio
async def test_learning_engine(mock_model_router, mock_memory_manager, dummy_history):
    engine = LearningEngine(mock_model_router, mock_memory_manager)
    engine.set_pipeline([
        LearningFilterStage(),
        ExtractionStage(mock_model_router),
        DuplicateDetectionStage(mock_memory_manager),
        ContradictionDetectionStage(mock_memory_manager),
        PromotionStage(mock_memory_manager)
    ])
    
    # Start engine processing task
    await engine.start()
    
    # Queue learning
    await engine.schedule_learning("conv1", dummy_history)
    
    # Wait for queue to be processed
    await asyncio.sleep(0.1)
    
    await engine.stop()
    
    # Verify end-to-end
    assert mock_model_router.generate.call_count == 1
    assert mock_memory_manager.retrieve.call_count == 4 # 2 from duplicate, 2 from contradiction (since 2 candidates extracted)
    assert mock_memory_manager.store.call_count == 2 # 2 candidates successfully made it through
