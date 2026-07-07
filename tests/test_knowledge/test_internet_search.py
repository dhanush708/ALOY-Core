import pytest
import pytest_asyncio
import re
from unittest.mock import AsyncMock, MagicMock

from tools.impl.web_search import WebSearchTool
from conversation.pipeline import ConversationContext
from conversation.state import ConversationState
from conversation.context_builder import ContextBuildStage
from conversation.context_intelligence import ContextIntelligenceEngine

# Test HTML representing DuckDuckGo search result structure (with rel="nofollow" before class="result__a")
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

@pytest.mark.asyncio
async def test_web_search_regex_parser():
    tool = WebSearchTool()
    
    # Verify the regex successfully extracts results from the DDG markup
    parsed_results = tool._parse_ddg_html(TEST_DDG_HTML)
    
    assert "NVIDIA GeForce Drivers" in parsed_results
    assert "https://www.nvidia.com/en-us/geforce/drivers/" in parsed_results
    assert "Download the latest official NVIDIA GeForce" in parsed_results
    
    assert "Download Python" in parsed_results
    assert "https://www.python.org/downloads/" in parsed_results
    assert "The latest release of Python is" in parsed_results

@pytest.mark.asyncio
async def test_live_search_triggers():
    # Setup mock conversation context and engine
    state = ConversationState(id="test_conv_search")
    
    # Test queries that MUST trigger internet search
    trigger_queries = [
        "Latest AI news",
        "Best games released in 2026",
        "Current NVIDIA driver version",
        "Latest Python release",
        "Weather today"
    ]
    
    # Test queries that must NOT trigger internet search
    non_trigger_queries = [
        "hello",
        "tell me a joke",
        "how does a quicksort work in python?"
    ]
    
    intel_engine = ContextIntelligenceEngine()
    stage = ContextBuildStage(intel_engine)
    
    # Setup mock app and knowledge router
    mock_app = MagicMock()
    mock_knowledge_router = MagicMock()
    # Mock query_escalation to return a fake verified answer
    mock_knowledge_router.query_escalation = AsyncMock(return_value={
        "answer": "Verified search results details.",
        "layer": "internet_search",
        "confidence": 0.95,
        "sources": [{"title": "Source 1", "url": "https://test.com"}]
    })
    mock_app.state.knowledge_router = mock_knowledge_router
    
    mock_conv_engine = MagicMock()
    mock_conv_engine.app = mock_app
    stage.conversation_engine = mock_conv_engine
    
    # 1. Assert triggers
    for q in trigger_queries:
        context = ConversationContext(state=state, user_message=q)
        # Clear mock call list
        mock_knowledge_router.query_escalation.reset_mock()
        
        await stage.process(context)
        
        # Verify knowledge router escalation was invoked
        mock_knowledge_router.query_escalation.assert_called_once_with(q)
        assert "<search_results" in context.full_prompt
        assert "Verified Web Search / Documentation Results:" in context.full_prompt
        
    # 2. Assert non-triggers
    for q in non_trigger_queries:
        context = ConversationContext(state=state, user_message=q)
        mock_knowledge_router.query_escalation.reset_mock()
        
        await stage.process(context)
        
        # Verify knowledge router was NOT invoked
        mock_knowledge_router.query_escalation.assert_not_called()
        assert "\n\n<search_results layer=" not in context.full_prompt
        assert "\n\n<search_results status=" not in context.full_prompt
