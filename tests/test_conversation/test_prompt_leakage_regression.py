"""
Comprehensive Prompt Leakage & Instruction Contamination Regression Tests.
Verifies:
1. First hi prompt and message formatting
2. Second hi prompt and message formatting
3. Hello after several turns
4. Normal technical question after several turns
5. History containing previous assistant responses formatted with role: assistant
6. PromptIntegrityFilter strips leaked delimiters, headers, and section banners
7. Messages array is always used for chat and never echoes system content
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from conversation.context_builder import ContextBuildStage
from conversation.context_intelligence import ContextIntelligenceEngine
from conversation.pipeline import ConversationContext, ConversationState
from conversation.history import ConversationMessage
from identity.integrity import PromptIntegrityFilter
from identity.engine import IdentityEngine
from memory.manager import MemoryManager
from database.connection import DatabaseConnectionPool
from models.router import ModelRouter


@pytest.mark.asyncio
async def test_first_hi_message_structure():
    """Verify first 'hi' creates structured role messages without leaking into user message."""
    intel = ContextIntelligenceEngine()
    stage = ContextBuildStage(intel)
    state = ConversationState(id="leak_test_1", turn_count=1)
    ctx = ConversationContext(state=state, user_message="hi", history=[])
    
    await stage.process(ctx)

    assert len(ctx.messages) == 2
    assert ctx.messages[0]["role"] == "system"
    assert ctx.messages[1]["role"] == "user"
    assert ctx.messages[1]["content"] == "hi"
    assert "<system>" not in ctx.messages[0]["content"]
    assert "</system>" not in ctx.messages[0]["content"]


@pytest.mark.asyncio
async def test_second_hi_message_structure_and_history():
    """Verify second 'hi' properly separates system, past user, past assistant, and current user."""
    intel = ContextIntelligenceEngine()
    stage = ContextBuildStage(intel)
    state = ConversationState(id="leak_test_2", turn_count=2)
    history = [
        ConversationMessage(id="m1", conversation_id=state.id, role="user", content="hi"),
        ConversationMessage(id="m2", conversation_id=state.id, role="assistant", content="Hey! How's it going?")
    ]
    ctx = ConversationContext(state=state, user_message="hi", history=history)
    
    await stage.process(ctx)

    assert len(ctx.messages) == 4
    assert ctx.messages[0]["role"] == "system"
    assert ctx.messages[1]["role"] == "user"
    assert ctx.messages[1]["content"] == "hi"
    assert ctx.messages[2]["role"] == "assistant"
    assert ctx.messages[2]["content"] == "Hey! How's it going?"
    assert ctx.messages[3]["role"] == "user"
    assert ctx.messages[3]["content"] == "hi"

    # Current user message must ONLY contain the user query, not internal prompt headers
    assert ctx.messages[3]["content"] == "hi"
    assert "End of updated instructions" not in ctx.messages[3]["content"]
    assert "revised instruction" not in ctx.messages[3]["content"]


@pytest.mark.asyncio
async def test_multi_turn_technical_question():
    """Verify multi-turn history with technical questions maintains strict role isolation."""
    intel = ContextIntelligenceEngine()
    stage = ContextBuildStage(intel)
    state = ConversationState(id="leak_test_3", turn_count=4)
    history = [
        ConversationMessage(id="m1", conversation_id=state.id, role="user", content="hi"),
        ConversationMessage(id="m2", conversation_id=state.id, role="assistant", content="Yo! What's up?"),
        ConversationMessage(id="m3", conversation_id=state.id, role="user", content="how are you"),
        ConversationMessage(id="m4", conversation_id=state.id, role="assistant", content="Doing great, ready to build."),
    ]
    ctx = ConversationContext(state=state, user_message="what is polymorphism", history=history)
    
    await stage.process(ctx)

    assert len(ctx.messages) == 6
    assert ctx.messages[0]["role"] == "system"
    assert ctx.messages[1]["role"] == "user"
    assert ctx.messages[1]["content"] == "hi"
    assert ctx.messages[2]["role"] == "assistant"
    assert ctx.messages[2]["content"] == "Yo! What's up?"
    assert ctx.messages[3]["role"] == "user"
    assert ctx.messages[3]["content"] == "how are you"
    assert ctx.messages[4]["role"] == "assistant"
    assert ctx.messages[4]["content"] == "Doing great, ready to build."
    assert ctx.messages[5]["role"] == "user"
    assert ctx.messages[5]["content"] == "what is polymorphism"


def test_prompt_integrity_filter_strips_delimiters_and_headers():
    """Verify PromptIntegrityFilter removes leaked instruction headers, delimiters, and XML tags."""
    pif = PromptIntegrityFilter()

    # 1. End of instructions leakage
    raw1 = "------ End of updated instructions ------\nPolymorphism is an OOP concept where..."
    cleaned1 = pif.sanitize_response_start(raw1)
    assert "End of updated instructions" not in cleaned1
    assert "Polymorphism is an OOP concept" in cleaned1

    # 2. System / Assistant role echo
    raw2 = "Assistant: Polymorphism is the ability of an object to take on many forms."
    cleaned2 = pif.sanitize_response_start(raw2)
    assert not cleaned2.startswith("Assistant:")
    assert "Polymorphism is the ability" in cleaned2

    # 3. XML prompt tag leakage
    raw3 = "<system>You are ALOY</system><identity><context state=\"neutral\" /></identity>Hello!"
    cleaned3 = pif.clean_text(raw3)
    assert "<system>" not in cleaned3
    assert "<identity>" not in cleaned3
    assert "<context" not in cleaned3
    assert cleaned3 == "Hello!"

    # 4. Personality styles section banner
    raw4 = "PERSONALITY STYLES & INTERACTION PRINCIPLES:\n- Active Listening\nHere is your answer."
    cleaned4 = pif.sanitize_response_start(raw4)
    assert "PERSONALITY STYLES" not in cleaned4


@pytest.mark.asyncio
async def test_identity_engine_build_prompt_context():
    """Verify IdentityEngine.build_prompt_context generates persona without shouting meta instructions."""
    db_pool = MagicMock()
    mock_conn = MagicMock()
    mock_conn.__enter__.return_value = mock_conn
    mock_conn.__exit__.return_value = None
    mock_conn.execute.return_value.fetchone.return_value = None
    mock_conn.execute.return_value.fetchall.return_value = []
    db_pool.get_read_connection.return_value = mock_conn

    mem_mgr = MagicMock()
    id_engine = IdentityEngine(db_pool, mem_mgr)
    
    # Turn 1
    state1 = ConversationState(id="test_id_state_1", turn_count=1)
    prompt_text_1 = await id_engine.build_prompt_context(state=state1)
    assert "ALOY" in prompt_text_1
    assert "Greet the user warmly" in prompt_text_1

    # Turn 2
    state2 = ConversationState(id="test_id_state_2", turn_count=2)
    prompt_text_2 = await id_engine.build_prompt_context(state=state2)
    assert "ALOY" in prompt_text_2
    assert "IMPORTANT: You are in an ONGOING conversation" not in prompt_text_2
    assert "Ongoing conversation:" in prompt_text_2
    assert "Greet the user warmly" not in prompt_text_2
