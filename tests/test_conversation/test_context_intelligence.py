import pytest
from datetime import datetime, timezone
from memory.types import Memory, ScoredMemory
from conversation.state import ConversationState
from conversation.history import ConversationMessage
from conversation.context_intelligence import ContextIntelligenceEngine

@pytest.fixture
def engine():
    return ContextIntelligenceEngine()

@pytest.fixture
def dummy_memories():
    m1 = Memory(id="m1", type="procedural", content="Python coding standards", tier="short_term", importance=0.8, created_at=datetime.now(timezone.utc).isoformat(), updated_at=datetime.now(timezone.utc).isoformat())
    m2 = Memory(id="m2", type="episodic", content="User likes dark mode", tier="short_term", importance=0.6, created_at=datetime.now(timezone.utc).isoformat(), updated_at=datetime.now(timezone.utc).isoformat())
    m3 = Memory(id="m3", type="profile", content="User name is Alice", tier="permanent", importance=0.9, created_at=datetime.now(timezone.utc).isoformat(), updated_at=datetime.now(timezone.utc).isoformat())
    
    return [
        ScoredMemory(memory=m1, score=0.7, relevance_details={}),
        ScoredMemory(memory=m2, score=0.6, relevance_details={}),
        ScoredMemory(memory=m3, score=0.8, relevance_details={}),
    ]

@pytest.fixture
def dummy_history():
    return [
        ConversationMessage(id="msg1", conversation_id="conv1", role="user", content="Hi", created_at=datetime.now(timezone.utc).isoformat()),
        ConversationMessage(id="msg2", conversation_id="conv1", role="assistant", content="Hello!", created_at=datetime.now(timezone.utc).isoformat()),
    ]

def test_token_manager(engine):
    tm = engine.token_manager
    text = "This is a short test."
    tokens = tm.count_tokens(text)
    assert tokens > 0
    
    # Test allocation
    allocated = tm.allocate_budget(100, {'a': 80, 'b': 40})
    assert allocated['a'] < 80
    assert allocated['b'] < 40
    assert sum(allocated.values()) <= 100

def test_context_ranker(engine, dummy_memories):
    ranker = engine.ranker
    
    # For coding request, m1 (procedural) should be boosted
    ranked_coding = ranker.rank_memories(dummy_memories, "How to write a loop?", "coding_request")
    assert ranked_coding[0][0].memory.id == "m1"
    
    # For memory request, m2 (episodic) or m3 (profile) might be boosted differently
    ranked_memory = ranker.rank_memories(dummy_memories, "What do I like?", "memory_query")
    # m3 (profile) starts at 0.8 * 0.8 = 0.64. m2 (episodic) 0.6 * 1.5 = 0.90. So m2 is highest.
    assert ranked_memory[0][0].memory.id == "m2"

def test_context_intelligence_engine(engine, dummy_memories, dummy_history):
    state = ConversationState(id="conv1", emotional_tone="neutral")
    
    pack = engine.build_context(
        query="Write some python code",
        intent="coding_request",
        conversation_state=state,
        system_prompt_template="System info here",
        identity_text="Identity info here",
        candidate_memories=dummy_memories,
        history=dummy_history,
        total_budget=8000
    )
    
    assert pack.system_prompt == "System info here"
    assert pack.identity_context == "Identity info here"
    # m1 should be included
    assert "m1" in pack.included_memory_ids
    assert "Python coding standards" in pack.memory_context
    assert "User: Hi" in pack.history_context
    assert pack.total_tokens > 0
    assert pack.token_budget_remaining > 0
    
    # The full prompt should assemble correctly
    full = pack.full_prompt
    assert "<system>" in full
    assert "<identity>" in full
    assert "<memories>" in full
    assert "<history>" in full
    assert "User: Hi" in full

def test_context_intelligence_compression(engine, dummy_memories, dummy_history):
    state = ConversationState(id="conv1")
    
    # Very small budget to force compression
    pack = engine.build_context(
        query="Write some python code",
        intent="coding_request",
        conversation_state=state,
        system_prompt_template="System info here",
        identity_text="Identity info here",
        candidate_memories=dummy_memories,
        history=dummy_history,
        total_budget=10 # Very tight budget
    )
    
    # Because budget is too small even with reserves, we expect history and memory to be dropped or empty
    assert len(pack.included_memory_ids) == 0
    assert pack.history_context == ""
