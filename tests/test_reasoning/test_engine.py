import pytest
import pytest_asyncio
import json
import asyncio
from unittest.mock import AsyncMock, MagicMock

from database.connection import DatabaseConnectionPool
from database.migrator import Migrator
from kernel.prompts import PromptRegistry
from kernel.event_bus import EventBus
from models.router import ModelRouter

from reasoning.templates import detect_strategy_and_template
from reasoning.verifier import SelfVerifier, VerificationResult
from reasoning.strategies import parse_think_block
from reasoning.engine import ReasoningEngine

# ======================================================================
# Fixtures
# ======================================================================

@pytest_asyncio.fixture
async def db_pool(tmp_path):
    db_path = str(tmp_path / "test_reasoning.db")
    pool = DatabaseConnectionPool(db_path)
    # Run migrations up to 007
    migrator = Migrator(pool, migrations_pkg="database.migrations")
    await migrator.migrate()
    yield pool

@pytest_asyncio.fixture
async def prompt_registry(db_pool):
    registry = PromptRegistry(db_pool)
    await registry.start()
    
    # Register mock prompts used in reasoning/verifier/debates
    registry.register("reasoning.simple", "1.0", "simple {query}", ["query"])
    registry.register("reasoning.clarify", "1.0", "clarify {query} {context}", ["query", "context"])
    registry.register("reasoning.design", "1.0", "design {query} {context} {clarification}", ["query", "context", "clarification"])
    registry.register("reasoning.critique", "1.0", "critique {query} {context} {strategy}", ["query", "context", "strategy"])
    registry.register("reasoning.formulate", "1.0", "formulate {query} {design} {critique}", ["query", "design", "critique"])
    registry.register("reasoning.debate_creator", "1.0", "creator {query} {context} {critic_response}", ["query", "context", "critic_response"])
    registry.register("reasoning.debate_critic", "1.0", "critic {query} {context} {creator_response}", ["query", "context", "creator_response"])
    registry.register("reasoning.debate_synthesize", "1.0", "synthesize {query} {context} {creator_response} {critic_response}", ["query", "context", "creator_response", "critic_response"])
    
    # Mock verifier prompt to return clean JSON
    registry.register(
        "reasoning.verifier",
        "1.0",
        "Verify {query} {output}",
        ["query", "output"]
    )
    
    # Mock correction prompt
    registry.register(
        "reasoning.correct",
        "1.0",
        "Correct {query} {output} {contradictions} {assumptions} {incomplete}",
        ["query", "output", "contradictions", "assumptions", "incomplete"]
    )
    
    yield registry

@pytest_asyncio.fixture
def mock_router():
    router = MagicMock(spec=ModelRouter)
    router.generate = AsyncMock(return_value="Mock response text")
    return router

@pytest_asyncio.fixture
def mock_event_bus():
    bus = MagicMock(spec=EventBus)
    bus.publish = AsyncMock()
    return bus

# ======================================================================
# Parse think block tests
# ======================================================================
def test_parse_think_block():
    text = "<think>\nThinking process...\n</think>\nFinal solution here."
    thought, output = parse_think_block(text)
    assert thought == "Thinking process..."
    assert output == "Final solution here."
    
    # Case insensitive check
    text_caps = "<THINK>\nThinking process CAPS...\n</THINK>\nFinal solution caps."
    thought_caps, output_caps = parse_think_block(text_caps)
    assert thought_caps == "Thinking process CAPS..."
    assert output_caps == "Final solution caps."
    
    # Empty think check
    no_think = "Just a direct response without thinking tags."
    thought_empty, output_direct = parse_think_block(no_think)
    assert thought_empty == ""
    assert output_direct == no_think

# ======================================================================
# Template detection tests
# ======================================================================
def test_detect_strategy_and_template():
    # Direct answer check
    strat, temp = detect_strategy_and_template("hi", {})
    assert strat == "direct_answer"
    
    # Debate check
    strat_deb, _ = detect_strategy_and_template("Please debate the advantages of SQLite vs PostgreSQL", {})
    assert strat_deb == "debate"
    
    # Tree check
    strat_tree, _ = detect_strategy_and_template("Explore alternate paths using a tree of options", {})
    assert strat_tree == "tree_of_thought"
    
    # Coding template check
    _, temp_code = detect_strategy_and_template("How do I write a fast python function to sort list", {})
    assert temp_code == "coding_plan"
    
    # Root cause check
    _, temp_bug = detect_strategy_and_template("Why did I get connection error crash on boot?", {})
    assert temp_bug == "root_cause_analysis"
    
    # Default exploratory check
    _, temp_exp = detect_strategy_and_template("Explain the origin of gravity and quantum mechanics", {})
    assert temp_exp == "exploratory_analysis"

# ======================================================================
# Self Verifier tests
# ======================================================================
@pytest.mark.asyncio
async def test_self_verifier_parsing(mock_router, prompt_registry):
    # Valid high confidence response
    json_response = (
        '{\n'
        '  "logical_contradictions": [],\n'
        '  "missing_assumptions": [],\n'
        '  "hallucination_risk": 0.05,\n'
        '  "incomplete_reasoning": [],\n'
        '  "confidence_score": 0.95,\n'
        '  "recommendations": []\n'
        '}'
    )
    mock_router.generate.return_value = json_response
    
    verifier = SelfVerifier(mock_router, prompt_registry)
    result = await verifier.verify("query", "output", [], {})
    
    assert result.is_valid is True
    assert result.confidence_score == 0.95
    assert result.hallucination_risk == 0.05
    assert len(result.logical_contradictions) == 0

@pytest.mark.asyncio
async def test_self_verifier_failed_confidence(mock_router, prompt_registry):
    # Low confidence response
    json_response = (
        '{\n'
        '  "logical_contradictions": ["Contradicts previous state"],\n'
        '  "missing_assumptions": ["Assumes DB is always connected"],\n'
        '  "hallucination_risk": 0.5,\n'
        '  "incomplete_reasoning": ["Step 3 skipped verification"],\n'
        '  "confidence_score": 0.35,\n'
        '  "recommendations": ["deeper_reasoning"]\n'
        '}'
    )
    mock_router.generate.return_value = json_response
    
    verifier = SelfVerifier(mock_router, prompt_registry)
    result = await verifier.verify("query", "output", [], {})
    
    assert result.is_valid is False
    assert result.confidence_score == 0.35
    assert "deeper_reasoning" in result.recommendations

# ======================================================================
# Subsystem Engine tests
# ======================================================================
@pytest.mark.asyncio
async def test_reasoning_engine_lifecycle(mock_router, prompt_registry, db_pool):
    engine = ReasoningEngine(mock_router, prompt_registry, db_pool=db_pool)
    
    assert (await engine.health_check()).value == "unhealthy"
    
    await engine.start()
    assert (await engine.health_check()).value == "healthy"
    
    metrics = engine.get_metrics()
    assert metrics["started"] is True
    assert metrics["execution_count"] == 0
    
    await engine.stop()
    assert (await engine.health_check()).value == "unhealthy"

@pytest.mark.asyncio
async def test_simple_strategy_execution(mock_router, prompt_registry, db_pool, mock_event_bus):
    mock_router.generate.return_value = "Basic explanation."
    
    engine = ReasoningEngine(mock_router, prompt_registry, event_bus=mock_event_bus, db_pool=db_pool)
    await engine.start()
    
    result = await engine.reason("What is 2+2?", {"verify": False, "strategy": "direct_answer"})
    
    assert result["final_output"] == "Basic explanation."
    assert result["strategy"] == "direct_answer"
    assert len(result["steps"]) == 1
    assert mock_event_bus.publish.call_count == 2 # Started & completed events

@pytest.mark.asyncio
async def test_deep_reasoning_strategy_execution(mock_router, prompt_registry, db_pool, mock_event_bus):
    mock_router.generate.return_value = "<think>\nThinking about physics...\n</think>\nGravity is curving spacetime."
    
    engine = ReasoningEngine(mock_router, prompt_registry, event_bus=mock_event_bus, db_pool=db_pool)
    await engine.start()
    
    result = await engine.reason("Explain gravity", {"verify": False, "strategy": "deep_reasoning"})
    
    assert result["final_output"] == "Gravity is curving spacetime."
    assert result["thought"] == "Thinking about physics..."
    assert result["strategy"] == "deep_reasoning"

@pytest.mark.asyncio
async def test_chain_of_thought_strategy_execution(mock_router, prompt_registry, db_pool, mock_event_bus):
    # Mock router to return specific step outcomes based on text matching or call index
    call_index = 0
    def mock_gen(task, prompt, options=None):
        nonlocal call_index
        call_index += 1
        return f"Stage output {call_index}"
        
    mock_router.generate.side_effect = mock_gen
    
    engine = ReasoningEngine(mock_router, prompt_registry, event_bus=mock_event_bus, db_pool=db_pool)
    await engine.start()
    
    # Exploratory template has 3 stages: clarify, decompose, synthesize
    result = await engine.reason(
        "Explain photosynthesis",
        {"verify": False, "strategy": "chain_of_thought", "template": "exploratory_analysis"}
    )
    
    assert result["strategy"] == "chain_of_thought"
    assert len(result["steps"]) == 3
    assert result["final_output"] == "Stage output 3"

@pytest.mark.asyncio
async def test_tree_of_thought_strategy_execution(mock_router, prompt_registry, db_pool, mock_event_bus):
    mock_router.generate.side_effect = [
        "BRANCH 1: SQL\nBRANCH 2: NoSQL\nBRANCH 3: File",  # Generate branches
        "SQL selected due to ACID compliance",            # Evaluate branches
        "Final solution: Use SQLite database."             # Execute chosen
    ]
    
    engine = ReasoningEngine(mock_router, prompt_registry, event_bus=mock_event_bus, db_pool=db_pool)
    await engine.start()
    
    result = await engine.reason("Select database strategy", {"verify": False, "strategy": "tree_of_thought"})
    
    assert result["strategy"] == "tree_of_thought"
    assert len(result["steps"]) == 3
    assert result["final_output"] == "Final solution: Use SQLite database."
    assert "SQL selected" in result["thought"]

@pytest.mark.asyncio
async def test_debate_strategy_execution(mock_router, prompt_registry, db_pool, mock_event_bus):
    mock_router.generate.side_effect = [
        "Creator proposal: use simple code.",  # Creator
        "Critic feedback: missing tests.",     # Critic
        "Final debate synthesis with tests."   # Synthesis
    ]
    
    engine = ReasoningEngine(mock_router, prompt_registry, event_bus=mock_event_bus, db_pool=db_pool)
    await engine.start()
    
    result = await engine.reason("Write binary search", {"verify": False, "strategy": "debate"})
    
    assert result["strategy"] == "debate"
    assert len(result["steps"]) == 3
    assert result["final_output"] == "Final debate synthesis with tests."

# ======================================================================
# Reasoning Memory & Promotion tests
# ======================================================================
@pytest.mark.asyncio
async def test_reasoning_memory_log_and_reuse(mock_router, prompt_registry, db_pool, mock_event_bus):
    mock_router.generate.return_value = "Solar power works via PV cells."
    
    engine = ReasoningEngine(mock_router, prompt_registry, event_bus=mock_event_bus, db_pool=db_pool)
    await engine.start()
    
    # 1. Execute first time (should run and log to DB)
    result1 = await engine.reason("Explain solar power", {"verify": False, "strategy": "direct_answer"})
    assert result1["duration_ms"] > 0.0
    
    # Verify row was created in reasoning_logs
    with db_pool.get_read_connection() as conn:
        row = conn.execute("SELECT * FROM reasoning_logs WHERE query = ?", ("Explain solar power",)).fetchone()
        assert row is not None
        assert row["use_count"] == 1
        assert row["strategy"] == "direct_answer"
        
    # 2. Execute second time (should hit cache/reuse path)
    result2 = await engine.reason("Explain solar power", {"verify": False, "strategy": "direct_answer"})
    assert result2["duration_ms"] == 0.0 # instant cache
    assert "PV cells" in result2["final_output"]
    assert "Re-used reasoning path" in result2["thought"]
    
    # Verify use count incremented to 2
    with db_pool.get_read_connection() as conn:
        row = conn.execute("SELECT use_count FROM reasoning_logs WHERE query = ?", ("Explain solar power",)).fetchone()
        assert row["use_count"] == 2

@pytest.mark.asyncio
async def test_reasoning_promotion_event(mock_router, prompt_registry, db_pool, mock_event_bus):
    mock_router.generate.return_value = "Wind power works via turbines."
    
    engine = ReasoningEngine(mock_router, prompt_registry, event_bus=mock_event_bus, db_pool=db_pool)
    await engine.start()
    
    # Run 1
    await engine.reason("Explain wind power", {"verify": False, "strategy": "direct_answer"})
    # Run 2 (cache reuse, count = 2)
    await engine.reason("Explain wind power", {"verify": False, "strategy": "direct_answer"})
    
    # Run 3 (cache reuse, count = 3 -> triggers promotion event)
    result = await engine.reason("Explain wind power", {"verify": False, "strategy": "direct_answer"})
    
    assert result["promoted"] is True
    
    # Sleep briefly to let event publish task execute
    await asyncio.sleep(0.1)
    
    # Verify that a memory.promoted event was published
    promoted_event = None
    for call in mock_event_bus.publish.call_args_list:
        event = call[0][0]
        if event.type == "memory.promoted":
            promoted_event = event
            
    assert promoted_event is not None
    assert promoted_event.data["query"] == "Explain wind power"
    assert promoted_event.data["final_output"] == "Wind power works via turbines."
