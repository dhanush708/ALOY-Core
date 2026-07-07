import pytest
import pytest_asyncio
import asyncio
import time
from unittest.mock import AsyncMock
from database.connection import DatabaseConnectionPool
from database.migrator import Migrator
from memory.manager import MemoryManager

@pytest_asyncio.fixture
async def memory_stress_manager(tmp_path):
    db_path = str(tmp_path / "test_memory_stress.db")
    pool = DatabaseConnectionPool(db_path)
    
    migrator = Migrator(pool, migrations_pkg="database.migrations")
    await migrator.migrate()
    
    manager = MemoryManager(pool)
    await manager.start()
    
    # Mock embedding generator
    manager.embeddings.generate = AsyncMock(return_value=[0.1] * 768)
    
    yield manager
    await manager.stop()
    await pool.stop()

@pytest.mark.asyncio
async def test_high_volume_memory_insertion_and_retrieval(memory_stress_manager):
    manager = memory_stress_manager
    
    # 1. Insert 1000 memories
    start_time = time.perf_counter()
    tasks = []
    for i in range(1000):
        tasks.append(
            manager.store(
                type="semantic",
                content=f"Observation {i}: Dhanush is working on coding task {i}.",
                importance=0.1 + (i % 9) * 0.1
            )
        )
    # Wait for all stores to complete
    await asyncio.gather(*tasks)
    duration = time.perf_counter() - start_time
    assert duration < 5.0
    
    # 2. Query concurrently
    query_tasks = []
    for i in range(100):
        query_tasks.append(manager.retrieve(f"Dhanush coding task {i}", limit=3))
    results = await asyncio.gather(*query_tasks)
    
    assert len(results) == 100
    for res in results:
        assert len(res) > 0

@pytest.mark.asyncio
async def test_memory_decay_stress(memory_stress_manager):
    manager = memory_stress_manager
    
    # Seed 50 low importance and 50 high importance protected memories
    for i in range(50):
        await manager.store("observation", f"Low importance {i}", importance=0.01)
        await manager.store("observation", f"Protected memory {i}", importance=0.9, is_protected=True)
        
    # Process decay
    decay_stats = await manager.process_decay()
    assert "decayed" in decay_stats
    
    # Protected memories should NEVER decay or be removed
    with manager.db_pool.get_read_connection() as conn:
        protected_cnt = conn.execute("SELECT COUNT(*) as cnt FROM memories WHERE is_protected = 1").fetchone()["cnt"]
        assert protected_cnt == 50

@pytest.mark.asyncio
async def test_contradiction_detection_load(memory_stress_manager):
    manager = memory_stress_manager
    
    # Seed a memory
    await manager.store("semantic", "The user lives in Paris.")
    
    # Mock model router for contradiction checks
    from models.router import ModelRouter
    model_router = AsyncMock()
    model_router.generate = AsyncMock(return_value="No contradiction")
    
    # Learning contradiction detector check
    from learning.stages.contradiction_detection import ContradictionDetectionStage
    stage = ContradictionDetectionStage(manager)
    from learning.pipeline import LearningContext, LearningCandidate
    candidate = LearningCandidate(
        content="The user lives in London.",
        type="semantic",
        confidence=0.9
    )
    context = LearningContext(
        conversation_id="c1",
        history=[],
        candidates=[candidate]
    )
    res_context = await stage.process(context)
    assert len(res_context.candidates) == 1
    assert res_context.candidates[0].content == "The user lives in London."
