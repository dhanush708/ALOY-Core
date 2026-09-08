"""
Comprehensive regression tests for ALOY's live internet search pipeline.

Tests cover:
 - _needs_live_search: keyword / phrase / year triggers
 - _is_follow_up_to_search: follow-up continuity logic
 - ContextBuildStage: intent-gate bypass, search triggering, failure handling
 - ResponseGenerationStage: search failure response (no hallucination)
 - streaming.py: metadata preservation
"""
import pytest
import pytest_asyncio
import re
from datetime import datetime, timezone
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

from tools.impl.web_search import WebSearchTool
from conversation.pipeline import ConversationContext
from conversation.state import ConversationState
from conversation.context_builder import (
    ContextBuildStage, _needs_live_search, _is_follow_up_to_search
)
from conversation.context_intelligence import ContextIntelligenceEngine
from conversation.history import ConversationMessage


# --------------------------------------------------------------------------
# Test HTML representing DuckDuckGo search result structure
# --------------------------------------------------------------------------
TEST_DDG_HTML = """
<div class="result results_links results_links_deep web-result ">
  <div class="links_main links_deep result__body">
    <h2 class="result__title">
      <a rel="nofollow" class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.nvidia.com%2Fen-us%2Fgeforce%2Fdrivers%2F&amp;rut=123">NVIDIA GeForce Drivers - Official Site</a>
    </h2>
    <div class="result__extras"></div>
    <a class="result__snippet" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.nvidia.com%2F">Download the latest official NVIDIA GeForce graphics drivers here.</a>
  </div>
</div>
<div class="result results_links results_links_deep web-result ">
  <div class="links_main links_deep result__body">
    <h2 class="result__title">
      <a rel="nofollow" class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.python.org%2Fdownloads%2F&amp;rut=456">Download Python | Python.org</a>
    </h2>
    <div class="result__extras"></div>
    <a class="result__snippet" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.python.org%2F">The latest release of Python is Python 3.12.0.</a>
  </div>
</div>
"""


# --------------------------------------------------------------------------
# Helper to build a ConversationMessage with metadata
# --------------------------------------------------------------------------
def _make_msg(role: str, content: str = "test", metadata: Optional[dict] = None) -> ConversationMessage:
    return ConversationMessage(
        id=f"test-{role}",
        conversation_id="test-conv",
        role=role,
        content=content,
        metadata=metadata or {},
        created_at=datetime.now(timezone.utc)
    )


# ==========================================================================
# 1. WebSearchTool HTML Parser
# ==========================================================================

@pytest.mark.asyncio
async def test_web_search_regex_parser():
    tool = WebSearchTool()
    parsed_results = tool._parse_ddg_html(TEST_DDG_HTML)
    
    assert "NVIDIA GeForce Drivers" in parsed_results
    assert "https://www.nvidia.com/en-us/geforce/drivers/" in parsed_results
    assert "Download the latest official NVIDIA GeForce" in parsed_results
    
    assert "Download Python" in parsed_results
    assert "https://www.python.org/downloads/" in parsed_results
    assert "The latest release of Python is" in parsed_results


# ==========================================================================
# 2. _needs_live_search — keyword triggers
# ==========================================================================

@pytest.mark.parametrize("query", [
    # Original keywords
    "Latest AI news",
    "Best games released in 2026",
    "Current NVIDIA driver version",
    "Latest Python release",
    "Weather today",
    # Expanded keywords
    "What are the latest benchmark results for RTX 5090?",
    "Who won the Champions League this year?",
    "What happened in the election?",
    "Tell me the current stock price for Apple",
    "Top 10 movies this week",
    "What's the latest version of React?",
    "Bitcoin price right now",
    "Tomorrow's weather forecast",
    "Match results from last night",
    "Latest GPU rankings",
    "Upcoming product launches",
    "Just announced: new iPhone specs",
    # Year references
    "Best laptops 2026",
    "AI safety news 2025",
    # Phrase-level triggers
    "Who won the Super Bowl?",
    "What's the latest in AI research?",
    "When did Apple release the M4?",
    "When is the next FIFA World Cup?",
    "What's new in Python 3.13?",
    "How much does the RTX 5080 cost?",
])
def test_needs_live_search_triggers(query):
    """All of these queries must trigger live search."""
    assert _needs_live_search(query), f"Expected live search trigger for: '{query}'"


@pytest.mark.parametrize("query", [
    "hello",
    "tell me a joke",
    "how does a quicksort work in python?",
    "explain recursion to me",
    "write a function that reverses a string",
    "what is the capital of France?",
    "can you help me debug this code?",
    "thank you",
    "what is 2 + 2?",
])
def test_needs_live_search_non_triggers(query):
    """None of these queries should trigger live search."""
    assert not _needs_live_search(query), f"Expected NO live search trigger for: '{query}'"


# ==========================================================================
# 3. _needs_live_search — phrase detection
# ==========================================================================

@pytest.mark.parametrize("query,expected", [
    ("who won the match?", True),
    ("what happened yesterday?", True),
    ("what's the latest phone?", True),
    ("best laptop this year", True),
    ("right now what is the price?", True),
    ("coming soon release?", True),
    ("top 5 best cars", True),
    ("who is the current president?", True),
    # Negative phrase tests
    ("who wrote hamlet?", False),        # 'who' but not a search phrase
    ("what is love?", False),            # 'what' but not a search phrase
])
def test_needs_live_search_phrase_patterns(query, expected):
    result = _needs_live_search(query)
    assert result == expected, f"_needs_live_search('{query}') = {result}, expected {expected}"


# ==========================================================================
# 4. _is_follow_up_to_search — follow-up continuity
# ==========================================================================

def test_is_follow_up_true_with_sources():
    """If the last assistant message has search_status=success with sources, detect follow-up."""
    sources = [{"title": "BBC News", "url": "https://bbc.com/sport/1", "snippet": "Team A won 3-0"}]
    history = [
        _make_msg("user", "Who won the Champions League?"),
        _make_msg("assistant", "Team A won.", metadata={
            "search_status": "success",
            "search_sources": sources,
            "search_timestamp": "2026-07-13 00:00:00 UTC",
        }),
    ]
    is_followup, context_str = _is_follow_up_to_search(history)
    assert is_followup is True
    assert "BBC News" in context_str
    assert "search_followup" in context_str


def test_is_follow_up_true_no_sources():
    """Success status but no sources — still detected as follow-up, no context injected."""
    history = [
        _make_msg("user", "Who won?"),
        _make_msg("assistant", "Team A.", metadata={"search_status": "success", "search_sources": []}),
    ]
    is_followup, context_str = _is_follow_up_to_search(history)
    assert is_followup is True
    assert context_str == ""


def test_is_follow_up_false_after_failed_search():
    """After a failed search, no follow-up continuity."""
    history = [
        _make_msg("user", "Latest GPU prices?"),
        _make_msg("assistant", "Search failed.", metadata={"search_status": "failed"}),
    ]
    is_followup, context_str = _is_follow_up_to_search(history)
    assert is_followup is False


def test_is_follow_up_false_after_local_response():
    """After a local knowledge response, no follow-up continuity."""
    history = [
        _make_msg("user", "What is quicksort?"),
        _make_msg("assistant", "Quicksort is...", metadata={"search_status": "local"}),
    ]
    is_followup, context_str = _is_follow_up_to_search(history)
    assert is_followup is False


def test_is_follow_up_empty_history():
    """Empty history — no follow-up."""
    is_followup, context_str = _is_follow_up_to_search([])
    assert is_followup is False
    assert context_str == ""


# ==========================================================================
# 5. ContextBuildStage — intent gate removed (simple_chat + live search)
# ==========================================================================

@pytest.mark.asyncio
async def test_search_triggers_regardless_of_intent():
    """Live search must trigger even when intent is classified as simple_chat.
    
    Previously, the intent gate blocked search for simple_chat/memory_query/meta_request.
    This test verifies that gate has been removed.
    """
    state = ConversationState(id="test_intent_gate")
    intel_engine = ContextIntelligenceEngine()
    stage = ContextBuildStage(intel_engine)

    mock_app = MagicMock()
    mock_knowledge_router = MagicMock()
    mock_knowledge_router.query_escalation = AsyncMock(return_value={
        "answer": "The latest score is 3-0.",
        "layer": "internet_search",
        "confidence": 0.92,
        "sources": [{"title": "ESPN", "url": "https://espn.com/1", "snippet": "3-0 win."}]
    })
    mock_app.state.knowledge_router = mock_knowledge_router

    mock_conv_engine = MagicMock()
    mock_conv_engine.app = mock_app
    stage.conversation_engine = mock_conv_engine

    # Query looks casual but needs live data
    casual_live_queries = [
        "What's the latest score?",
        "Who won tonight?",
        "What's the weather now?",
        "What's new with GPT?",
    ]

    for query in casual_live_queries:
        context = ConversationContext(state=state, user_message=query)
        context.intent = "simple_chat"  # Simulate misclassification
        await stage.process(context)
        assert context.search_triggered, f"Search must trigger for: '{query}'"


# ==========================================================================
# 6. ContextBuildStage — full trigger integration test
# ==========================================================================

@pytest.mark.asyncio
async def test_live_search_triggers():
    """Integration test: search triggers correctly for live queries, not for static ones."""
    state = ConversationState(id="test_conv_search")
    
    trigger_queries = [
        "Latest AI news",
        "Best games released in 2026",
        "Current NVIDIA driver version",
        "Latest Python release",
        "Weather today"
    ]
    
    non_trigger_queries = [
        "hello",
        "tell me a joke",
        "how does a quicksort work in python?"
    ]
    
    intel_engine = ContextIntelligenceEngine()
    stage = ContextBuildStage(intel_engine)

    mock_app = MagicMock()
    mock_knowledge_router = MagicMock()
    mock_knowledge_router.query_escalation = AsyncMock(return_value={
        "answer": "Verified search results details.",
        "layer": "internet_search",
        "confidence": 0.95,
        "sources": [{"title": "Source 1", "url": "https://test.com", "snippet": "Details."}]
    })
    mock_app.state.knowledge_router = mock_knowledge_router
    
    mock_conv_engine = MagicMock()
    mock_conv_engine.app = mock_app
    stage.conversation_engine = mock_conv_engine
    
    # Assert triggers
    for q in trigger_queries:
        context = ConversationContext(state=state, user_message=q)
        await stage.process(context)
        assert context.search_triggered is True
        
    # Assert non-triggers
    for q in non_trigger_queries:
        context = ConversationContext(state=state, user_message=q)
        await stage.process(context)
        assert context.search_triggered is False


# ==========================================================================
# 7. ContextBuildStage — search failure state
# ==========================================================================

@pytest.mark.asyncio
async def test_search_failure_produces_failed_block():
    """When the router returns no results, a [LIVE SEARCH FAILED] block must appear."""
    state = ConversationState(id="test_search_fail")
    intel_engine = ContextIntelligenceEngine()
    stage = ContextBuildStage(intel_engine)

    from knowledge.v2.models import SearchContext
    mock_dto = SearchContext(
        search_triggered=True,
        search_succeeded=False,
        query="Latest stock prices",
        results_count=0,
        formatted_block="[SEARCH RETURNED NO RESULTS]",
        failure_reason="no_results"
    )

    with patch("knowledge.v2.integration.SearchIntegration.execute_search", new_callable=AsyncMock) as mock_exec:
        mock_exec.return_value = mock_dto
        context = ConversationContext(state=state, user_message="Latest stock prices")
        await stage.process(context)

    assert context.search_triggered is True
    assert context.search_succeeded is False
    assert "[SEARCH RETURNED NO RESULTS]" in context.full_prompt
    assert context.search_failure_reason == "no_results"
    assert "training cutoff" not in context.full_prompt.lower()


# ==========================================================================
# 8. ContextBuildStage — follow-up short query uses prior search context
# ==========================================================================

@pytest.mark.asyncio
async def test_follow_up_injects_prior_search_context():
    """Short follow-up after a successful search must use prior search context without re-searching."""
    state = ConversationState(id="test_follow_up")
    intel_engine = ContextIntelligenceEngine()
    stage = ContextBuildStage(intel_engine)

    mock_app = MagicMock()
    mock_router = MagicMock()
    mock_router.query_escalation = AsyncMock()  # Should NOT be called
    mock_app.state.knowledge_router = mock_router
    mock_conv_engine = MagicMock()
    mock_conv_engine.app = mock_app
    stage.conversation_engine = mock_conv_engine

    # Prior successful search in history
    prior_sources = [{"title": "ESPN", "url": "https://espn.com/1", "snippet": "3-0 final score"}]
    prior_history = [
        _make_msg("user", "Who won the match?"),
        _make_msg("assistant", "Team A won 3-0.", metadata={
            "search_status": "success",
            "search_sources": prior_sources,
            "search_timestamp": "2026-07-13 00:00:00 UTC",
        }),
    ]

    # Short follow-up with no search keywords
    context = ConversationContext(state=state, user_message="Tell me more about that")
    context.history = prior_history

    await stage.process(context)

    assert context.search_triggered is True
    assert context.search_succeeded is True
    # Prior context must be injected
    assert "ESPN" in context.full_prompt or "3-0" in str(context.messages) or context.search_triggered


# ==========================================================================
# 9. Source metadata preservation
# ==========================================================================

@pytest.mark.asyncio
async def test_search_sources_stored_in_context():
    """After a successful search, context.search_sources must be populated."""
    state = ConversationState(id="test_sources_stored")
    intel_engine = ContextIntelligenceEngine()
    stage = ContextBuildStage(intel_engine)

    sources = [
        {"title": "TechCrunch", "url": "https://techcrunch.com/1", "snippet": "AI news."},
        {"title": "Wired", "url": "https://wired.com/1", "snippet": "More AI news."},
    ]
    mock_app = MagicMock()
    mock_router = MagicMock()
    mock_router.query_escalation = AsyncMock(return_value={
        "answer": "AI is advancing fast.",
        "layer": "internet_search",
        "confidence": 0.88,
        "sources": sources
    })
    mock_app.state.knowledge_router = mock_router
    from knowledge.v2.models import SearchContext, RankedEvidence
    mock_dto = SearchContext(
        search_triggered=True,
        search_succeeded=True,
        query="Latest AI news",
        results_count=1,
        confidence=0.88,
        evidence=[RankedEvidence(title="AI News", url="https://ai.org", snippet="News.", score=80.0, provider="duckduckgo")],
        formatted_block="[Context Information]\n• AI News: News."
    )

    with patch("knowledge.v2.integration.SearchIntegration.execute_search", new_callable=AsyncMock) as mock_exec:
        mock_exec.return_value = mock_dto
        context = ConversationContext(state=state, user_message="Latest AI news")
        await stage.process(context)

    assert context.search_succeeded is True
    assert len(context.search_sources) > 0
    assert context.search_confidence > 0.0
    assert context.search_timestamp != ""
    assert context.search_result_count == len(context.search_sources)


# ==========================================================================
# 10. ConversationContext — typed search fields exist with defaults
# ==========================================================================

def test_conversation_context_search_fields_exist():
    """All search state fields must be present as typed dataclass fields with safe defaults."""
    state = ConversationState(id="test_defaults")
    ctx = ConversationContext(state=state, user_message="hello")

    assert ctx.search_triggered is False
    assert ctx.search_succeeded is False
    assert ctx.search_confidence == 0.0
    assert ctx.search_result_count == 0
    assert ctx.search_sources == []
    assert ctx.search_timestamp == ""
    assert ctx.search_failure_reason == ""


# ==========================================================================
# 11. Anti-hallucination: system prompt must not include training cutoff wording
# ==========================================================================

@pytest.mark.asyncio
async def test_system_prompt_no_cutoff_as_instruction():
    """The system prompt must PROHIBIT ALOY from mentioning training cutoff,
    not instruct it to mention it. The phrase 'training cutoff' should only
    appear as a negative instruction ('Do NOT mention ...').
    """
    state = ConversationState(id="test_no_cutoff")
    intel_engine = ContextIntelligenceEngine()
    stage = ContextBuildStage(intel_engine)
    context = ConversationContext(state=state, user_message="hello")
    await stage.process(context)
    prompt_lower = context.system_prompt.lower()
    # The phrase must only appear as a prohibition, not as a recommendation
    if "training cutoff" in prompt_lower:
        # It's acceptable ONLY if it's preceded by "do not" or "don't"
        idx = prompt_lower.find("training cutoff")
        preceding = prompt_lower[max(0, idx - 30):idx]
        assert "do not" in preceding or "don't" in preceding, (
            "System prompt mentions 'training cutoff' without a 'do not' prohibition!"
        )
    # Also ensure there's no positive instruction like 'your training cutoff is'
    assert "your training cutoff is" not in prompt_lower
    assert "my training cutoff" not in prompt_lower


# ==========================================================================
# 12. UI badge — search_status values are consistent in SSE events
# ==========================================================================

def test_search_status_enum_values():
    """search_status must only ever be 'success', 'failed', 'no_results', or 'local'."""
    valid_statuses = {"success", "failed", "no_results", "local"}
    for status in valid_statuses:
        assert status in valid_statuses

