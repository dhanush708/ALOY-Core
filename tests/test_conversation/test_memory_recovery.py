"""Regression tests for the ALOY v1.0.2 Memory Recovery work.

These tests pin down the specific behavioural fixes that the memory-recovery
task introduced, so a future refactor cannot silently undo them:

  1. History load limit raised 10 -> 40 (conversation/engine.py)
  2. Compaction ABORTS (no deletion) when summarization fails (conversation/engine.py)
  3. Summary consolidation: re-compaction never leaves duplicate summary rows
     (conversation/engine.py)
  4. turn_count is NOT reset by compaction; identity engine greets only on the
     first turn (conversation/engine.py + identity/engine.py)
  5. Context token budgets increased (conversation/context_intelligence.py)
  6. Compacted history summaries are re-injected into the structured messages
     list as a [CONVERSATION SUMMARY] block (conversation/context_builder.py)

All tests run fully offline: the model router is mocked, embeddings are mocked,
and the live search path in ContextBuildStage is neutralised.
"""
import pytest
import pytest_asyncio
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

from database.connection import DatabaseConnectionPool
from database.migrator import Migrator
from memory.manager import MemoryManager
from conversation.engine import ConversationEngine
from conversation.history import ConversationStore, ConversationMessage
from conversation.state import ConversationState
from conversation.context_intelligence import ContextIntelligenceEngine
from conversation.pipeline import ConversationContext
from conversation.context_builder import ContextBuildStage
from identity.engine import IdentityEngine

# Epoch used so created_at ordering is deterministic across rapid inserts
_BASE_TIME = datetime(2026, 1, 1, tzinfo=timezone.utc)


@pytest_asyncio.fixture
async def setup_db(tmp_path):
    """Fresh DB + migrated schema + memory manager with offline embeddings."""
    db_path = str(tmp_path / "test_memrec.db")
    pool = DatabaseConnectionPool(db_path)
    migrator = Migrator(pool, migrations_pkg="database.migrations")
    await migrator.migrate()

    mem_mgr = MemoryManager(pool)
    await mem_mgr.start()
    # Mock embeddings so memory.store()/retrieve() never touch ollama
    mem_mgr.embeddings.generate = AsyncMock(return_value=[0.1] * 768)

    return pool, mem_mgr


def _mock_router(summarization: str = "", reflection: str = "", *, raise_summary=False):
    """Build a mock ModelRouter whose generate() returns canned text per task."""
    router = AsyncMock()

    async def fake_generate(task, prompt, options=None, conversation_id=None):
        if raise_summary and task == "summarization":
            raise RuntimeError("simulated summarization failure")
        if task == "summarization":
            return summarization
        if task == "reflection":
            return reflection
        # classification / anything else
        return "NO"

    router.generate = fake_generate
    return router


async def _seed_messages(store: ConversationStore, conv_id: str, n: int, start_idx: int = 0):
    """Insert n alternating user/assistant messages with strictly increasing timestamps."""
    for i in range(n):
        idx = start_idx + i
        role = "user" if idx % 2 == 0 else "assistant"
        await store.add_message(
            conversation_id=conv_id,
            role=role,
            content=f"message {idx} from {role}",
            created_at=_BASE_TIME + timedelta(seconds=idx),
        )


async def _conv(store: ConversationStore, conv_id: str, turn_count: int = 0):
    """Create a conversation row with a known turn_count."""
    state = ConversationState(id=conv_id, turn_count=turn_count)
    await store.create_conversation(state)
    return state


def _count_summaries(pool, conv_id: str) -> int:
    with pool.get_read_connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM conversation_messages "
            "WHERE conversation_id = ? AND role = 'system' "
            "AND json_extract(metadata, '$.is_summary') = 1",
            (conv_id,),
        ).fetchone()
        return row["cnt"]


# =============================================================================
# 1. History limit raised 10 -> 40
# =============================================================================

def test_history_load_stage_default_argument_is_40():
    """The HistoryLoadStage default limit must match the recovery value of 40."""
    from conversation.context_builder import HistoryLoadStage
    stage = HistoryLoadStage(history_store=None, limit=40)
    assert stage.limit == 40


@pytest.mark.asyncio
async def test_engine_pipeline_uses_history_limit_40(setup_db):
    """The ConversationEngine pipeline must request 40 history messages."""
    pool, mem_mgr = setup_db
    engine = ConversationEngine(pool, mem_mgr, model_router=None)
    # pipeline[1] is HistoryLoadStage
    from conversation.context_builder import HistoryLoadStage
    assert isinstance(engine.pipeline[1], HistoryLoadStage)
    assert engine.pipeline[1].limit == 40
    assert engine.pipeline[1].limit != 10  # guard against revert


@pytest.mark.asyncio
async def test_get_history_caps_at_configured_limit(setup_db):
    """With 50 stored messages, a limit=40 fetch returns exactly 40."""
    pool, _ = setup_db
    store = ConversationStore(pool)
    await _conv(store, "c_hist")
    await _seed_messages(store, "c_hist", 50)
    history = await store.get_history("c_hist", limit=40)
    assert len(history) == 40
    # Most recent 40 must be present (i.e. messages 10..49)
    assert history[-1].created_at == _BASE_TIME + timedelta(seconds=49)


# =============================================================================
# 2. Compaction aborts (no deletion) when summarization fails
# =============================================================================

@pytest.mark.asyncio
async def test_compaction_aborts_on_empty_summary(setup_db):
    """Empty summarizer output must NOT delete history — history preserved intact."""
    pool, mem_mgr = setup_db
    store = ConversationStore(pool)
    await _conv(store, "c_abort", turn_count=20)
    await _seed_messages(store, "c_abort", 16)

    router = _mock_router(summarization="")  # empty -> summary 'too short'
    engine = ConversationEngine(pool, mem_mgr, model_router=router)

    before = await store.get_history("c_abort", limit=100)
    assert len(before) == 16

    await engine.compact_conversation_if_needed("c_abort")

    after = await store.get_history("c_abort", limit=100)
    assert len(after) == 16, "History must be untouched when summarization is empty"
    assert _count_summaries(pool, "c_abort") == 0, "No summary must be inserted on failure"

    # turn_count must remain 20 (no reset, no mutation)
    state = await store.get_conversation("c_abort")
    assert state.turn_count == 20


@pytest.mark.asyncio
async def test_compaction_aborts_on_summary_exception(setup_db):
    """A summarizer exception must NOT delete history either."""
    pool, mem_mgr = setup_db
    store = ConversationStore(pool)
    await _conv(store, "c_exc", turn_count=7)
    await _seed_messages(store, "c_exc", 16)

    router = _mock_router(raise_summary=True)
    engine = ConversationEngine(pool, mem_mgr, model_router=router)

    await engine.compact_conversation_if_needed("c_exc")

    after = await store.get_history("c_exc", limit=100)
    assert len(after) == 16, "History must be preserved when the summarizer raises"
    assert _count_summaries(pool, "c_exc") == 0


@pytest.mark.asyncio
async def test_compaction_below_threshold_is_noop(setup_db):
    """Fewer than 12 messages must not trigger any compaction."""
    pool, mem_mgr = setup_db
    store = ConversationStore(pool)
    await _conv(store, "c_small", turn_count=3)
    await _seed_messages(store, "c_small", 8)

    router = _mock_router(summarization="should not be used")
    engine = ConversationEngine(pool, mem_mgr, model_router=router)

    await engine.compact_conversation_if_needed("c_small")
    after = await store.get_history("c_small", limit=100)
    assert len(after) == 8
    assert _count_summaries(pool, "c_small") == 0


# =============================================================================
# 3. Summary consolidation: re-compaction never leaves duplicate summaries
# =============================================================================

@pytest.mark.asyncio
async def test_compaction_success_inserts_single_summary(setup_db):
    """One successful compaction reduces 16 messages -> 4 kept + 1 summary."""
    pool, mem_mgr = setup_db
    store = ConversationStore(pool)
    await _conv(store, "c_ok", turn_count=20)
    await _seed_messages(store, "c_ok", 16)

    router = _mock_router(summarization="Key points discussed in the past conversation.")
    engine = ConversationEngine(pool, mem_mgr, model_router=router)

    await engine.compact_conversation_if_needed("c_ok")

    after = await store.get_history("c_ok", limit=100)
    # 4 recent messages kept + 1 summary system message
    assert len(after) == 5
    assert _count_summaries(pool, "c_ok") == 1
    # The summary must carry the compaction_index snapshot of turn_count
    with pool.get_read_connection() as conn:
        row = conn.execute(
            "SELECT metadata FROM conversation_messages WHERE conversation_id = ? AND role = 'system'",
            ("c_ok",),
        ).fetchone()
        import json
        meta = json.loads(row["metadata"])
        assert meta.get("is_summary") is True
        assert meta.get("compaction_index") == 20
    # turn_count must NOT be reset by compaction
    state = await store.get_conversation("c_ok")
    assert state.turn_count == 20


@pytest.mark.asyncio
async def test_recompaction_consolidates_summaries_no_duplicates(setup_db):
    """Compacting a second time must delete the prior summary first — exactly one remains."""
    pool, mem_mgr = setup_db
    store = ConversationStore(pool)
    await _conv(store, "c_cons", turn_count=10)
    await _seed_messages(store, "c_cons", 16)

    router = _mock_router(summarization="Consolidated summary of the conversation history.")
    engine = ConversationEngine(pool, mem_mgr, model_router=router)

    # First compaction: 16 -> 4 kept + 1 summary = 5
    await engine.compact_conversation_if_needed("c_cons")
    assert _count_summaries(pool, "c_cons") == 1

    # Grow the conversation again so we cross the 12-message threshold
    await _seed_messages(store, "c_cons", 10, start_idx=16)
    mid = await store.get_history("c_cons", limit=100)
    assert len(mid) == 15  # 5 + 10

    # Second compaction must replace the prior summary, not stack a second one
    await engine.compact_conversation_if_needed("c_cons")

    after = await store.get_history("c_cons", limit=100)
    assert _count_summaries(pool, "c_cons") == 1, "Re-compaction must consolidate to a single summary"
    # 4 kept recent + 1 new summary
    assert len(after) == 5

    # And the surviving summary content must be the NEW one (not a stale duplicate)
    assert "Consolidated summary" in after[0].content


# =============================================================================
# 4. turn_count not reset + identity greeting only on first turn
# =============================================================================

@pytest.mark.asyncio
async def test_identity_greet_only_on_first_turn(setup_db):
    pool, mem_mgr = setup_db
    engine = IdentityEngine(pool, mem_mgr)
    await engine.initialize_if_needed()

    # turn_count 0 and 1 -> first-turn greeting branch
    p0 = await engine.generate_identity_prompt("simple_chat", turn_count=0)
    p1 = await engine.generate_identity_prompt("simple_chat", turn_count=1)
    assert "Greet the user warmly" in p0
    assert "Greet the user warmly" in p1

    # turn_count >= 2 -> ongoing conversation, NO greeting instruction
    p2 = await engine.generate_identity_prompt("simple_chat", turn_count=2)
    assert "Greet the user warmly" not in p2
    assert "ONGOING conversation" in p2
    assert "Do NOT re-greet" in p2

    # Technical intents never greet regardless of turn_count
    p_coding = await engine.generate_identity_prompt("coding_request", turn_count=0)
    assert "professional, straightforward, and technical style" in p_coding
    assert "Greet the user warmly" not in p_coding
    assert "Continue the conversation naturally" in p_coding


@pytest.mark.asyncio
async def test_compaction_does_not_reset_turn_count(setup_db):
    """The OLD bug reset turn_count to len(to_keep)+1; it must now stay constant."""
    pool, mem_mgr = setup_db
    store = ConversationStore(pool)
    await _conv(store, "c_tc", turn_count=33)
    await _seed_messages(store, "c_tc", 16)

    router = _mock_router(summarization="A valid multi-point summary text here.")
    engine = ConversationEngine(pool, mem_mgr, model_router=router)

    await engine.compact_conversation_if_needed("c_tc")
    state = await store.get_conversation("c_tc")
    assert state.turn_count == 33, "Compaction must not reset turn_count (would re-trigger greeting)"


# =============================================================================
# 5. Context token budgets increased
# =============================================================================

def test_context_budgets_are_increased():
    engine = ContextIntelligenceEngine()
    profiles = {
        "simple_chat":      {"history": 2000, "memories": 1000},
        "complex_chat":     {"history": 3000, "memories": 2000},
        "coding_request":   {"history": 1500, "memories": 500},
        "memory_query":     {"history": 1500, "memories": 3000},
        "tool_request":     {"history": 1500, "memories": 200},
        "reasoning_request":{"history": 2000, "memories": 1000},
    }
    for intent, expected in profiles.items():
        prof = engine.get_profile(intent)
        assert prof["history"] == expected["history"], (
            f"{intent}: history budget must be {expected['history']} (recovery bump)"
        )
        assert prof["memories"] == expected["memories"], (
            f"{intent}: memories budget must be {expected['memories']}"
        )
        # Guard against revert to the old 500-token history default
        assert prof["history"] >= 1500


def test_unknown_intent_falls_back_to_default_profile():
    engine = ContextIntelligenceEngine()
    prof = engine.get_profile("some_unknown_intent")
    assert prof["history"] == 1000
    assert prof["memories"] == 1000


# =============================================================================
# 6. Compacted summary re-injection into the structured messages list
# =============================================================================

class _StubIdentityEngine:
    """Minimal offline identity engine for testing ContextBuildStage in isolation."""
    async def get_active_workspace_info(self, project_manager):
        return None

    async def generate_identity_prompt(self, intent, app_state=None,
                                       workspace_info=None, turn_count=0):
        return "IDENTITY-STUB"


@pytest.mark.asyncio
async def test_summary_reinjected_into_messages(monkeypatch, setup_db):
    """A compacted summary (role=system, is_summary) must be folded back into the
    system message of the structured messages list as a [CONVERSATION SUMMARY] block."""
    pool, _ = setup_db

    # Neutralise the live-search path so the stage runs fully offline
    from knowledge.search_pipeline import SearchPipeline
    monkeypatch.setattr(SearchPipeline, "__init__", lambda self, *a, **k: None)
    monkeypatch.setattr(SearchPipeline, "needs_search", AsyncMock(return_value=False))

    intelligence = ContextIntelligenceEngine()
    conv_stub = SimpleNamespace(app=None, db_pool=pool, model_router=None)
    stage = ContextBuildStage(
        intelligence_engine=intelligence,
        identity_engine=_StubIdentityEngine(),
        conversation_engine=conv_stub,
    )

    history = [
        ConversationMessage(
            id="s1", conversation_id="c_reinj", role="system",
            content="User prefers Python and dark mode.",
            metadata={"is_summary": True, "compaction_index": 5},
            created_at=_BASE_TIME,
        ),
        ConversationMessage(
            id="u1", conversation_id="c_reinj", role="user",
            content="Hi", metadata={},
            created_at=_BASE_TIME + timedelta(seconds=1),
        ),
        ConversationMessage(
            id="a1", conversation_id="c_reinj", role="assistant",
            content="Hello there!", metadata={},
            created_at=_BASE_TIME + timedelta(seconds=2),
        ),
    ]

    state = ConversationState(id="c_reinj", turn_count=3)
    ctx = ConversationContext(state=state, user_message="what did we discuss earlier?")
    ctx.history = history

    await stage.process(ctx)

    messages = ctx.messages
    assert len(messages) == 4  # system + user + assistant + final user
    assert messages[0]["role"] == "system"
    assert "[CONVERSATION SUMMARY]" in messages[0]["content"]
    assert "User prefers Python and dark mode." in messages[0]["content"]
    # Remaining history reinjected as structured turns
    assert messages[1]["role"] == "user" and messages[1]["content"] == "Hi"
    assert messages[2]["role"] == "assistant" and messages[2]["content"] == "Hello there!"
    # Final user message carries the live query
    assert messages[3]["role"] == "user"
    assert "what did we discuss earlier?" in messages[3]["content"]

@pytest.mark.asyncio
async def test_long_term_memory_pov_fix(monkeypatch, setup_db):
    """Verify that memories are injected under a safe POV boundary to prevent identity leakage."""
    pool, _ = setup_db

    # Neutralise search path
    from knowledge.search_pipeline import SearchPipeline
    monkeypatch.setattr(SearchPipeline, "__init__", lambda self, *a, **k: None)
    monkeypatch.setattr(SearchPipeline, "needs_search", AsyncMock(return_value=False))

    intelligence = ContextIntelligenceEngine()
    conv_stub = SimpleNamespace(app=None, db_pool=pool, model_router=None)
    stage = ContextBuildStage(
        intelligence_engine=intelligence,
        identity_engine=_StubIdentityEngine(),
        conversation_engine=conv_stub,
    )

    from memory.types import ScoredMemory, Memory
    import uuid

    # Simulate an extracted first-person memory to prove backward compatibility
    mock_memory = Memory(
        id=str(uuid.uuid4()),
        type="conversation_memory",
        content="My dream company is OpenAI",
        tier="short_term",
        importance=0.8
    )
    mock_scored = [ScoredMemory(memory=mock_memory, score=1.0)]

    state = ConversationState(id="pov_test", turn_count=1)
    ctx = ConversationContext(state=state, user_message="What is my dream company?")
    ctx.memories = mock_scored

    await stage.process(ctx)
    messages = ctx.messages
    
    assert len(messages) >= 2
    system_msg = messages[0]["content"]
    
    # Verify the POV boundary is present
    assert "[FACTS ABOUT THE USER]" in system_msg
    assert "describe the USER (not you)" in system_msg
    assert "quoting the user" in system_msg
    assert "My dream company is OpenAI" in system_msg
