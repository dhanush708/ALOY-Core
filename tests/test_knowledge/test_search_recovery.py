"""
ALOY v1.0.2 - Search Reliability Recovery Regression Tests
===========================================================
Covers 15 failure scenarios. All tests are fully offline.
"""
import asyncio
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from knowledge.search_pipeline import SearchPipeline
from conversation.pipeline import ConversationContext
from conversation.state import ConversationState
from conversation.context_builder import ContextBuildStage
from conversation.context_intelligence import ContextIntelligenceEngine

_GOOD_RESULT = [
    {
        "title": "Example Source",
        "url": "https://reuters.com/article/1",
        "snippet": "Factual content retrieved in 2026.",
        "score": 80.0,
        "confidence_rating": "High",
        "authority": 70.0,
        "freshness": 10.0,
        "relevance": 0.0,
        "timestamp": "2026-01-01 00:00:00 UTC",
    }
]

_CANONICAL_FAILURE = "I could not find enough reliable evidence."


def _make_pipeline(search_tool=None, model_router=None, db_pool=None):
    pool = db_pool or MagicMock()
    with patch("knowledge.search_pipeline.ResearchCache") as MockCache:
        MockCache.return_value.get.return_value = None
        MockCache.return_value.set.return_value = None
        sp = SearchPipeline(pool, model_router, search_tool=search_tool or MagicMock())
        sp.cache = MockCache.return_value
    return sp


# ---------------------------------------------------------------------------
# 1. Network timeout in _execute_single_query
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_execute_single_query_network_timeout():
    """If search_tool.execute hangs, _execute_single_query must return [] within timeout."""
    mock_tool = MagicMock()
    mock_tool.execute = AsyncMock(side_effect=asyncio.TimeoutError)

    sp = _make_pipeline(search_tool=mock_tool)

    with patch("knowledge.search_pipeline.asyncio.wait_for", side_effect=asyncio.TimeoutError):
        result = await sp._execute_single_query("latest news")

    assert result == [], "Network timeout must return [], not raise"


# ---------------------------------------------------------------------------
# 2. Network exception in _execute_single_query
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_execute_single_query_network_exception():
    """Any exception from the search tool must be caught and return []."""
    mock_tool = MagicMock()
    mock_tool.execute = AsyncMock(side_effect=ConnectionError("DNS failure"))

    sp = _make_pipeline(search_tool=mock_tool)
    result = await sp._execute_single_query("stock prices")

    assert result == [], "Network exception must return [] without propagating"


# ---------------------------------------------------------------------------
# 3. Empty results from search tool
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_execute_single_query_empty_results():
    """A 'No results' response from search tool returns []."""
    mock_tool = MagicMock()
    mock_tool.execute = AsyncMock(return_value="No results found.")

    sp = _make_pipeline(search_tool=mock_tool)
    result = await sp._execute_single_query("extremely obscure query zxqv")

    assert result == []


# ---------------------------------------------------------------------------
# 4. Circuit breaker: opens after max_failures
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_circuit_breaker_opens_after_max_failures():
    """After _max_failures consecutive failures, circuit opens and suppresses calls."""
    mock_tool = MagicMock()
    mock_tool.execute = AsyncMock(return_value="No results found.")

    sp = _make_pipeline(search_tool=mock_tool)
    assert sp._max_failures == 3
    assert not sp._circuit_open()

    for _ in range(sp._max_failures):
        sp._record_search_failure()

    assert sp._circuit_open(), "Circuit must be open after max_failures failures"

    mock_tool.execute.reset_mock()
    result = await sp.execute_with_retry("bitcoin price")
    assert result == []
    mock_tool.execute.assert_not_called()


# ---------------------------------------------------------------------------
# 5. Circuit breaker: resets on success
# ---------------------------------------------------------------------------

def test_circuit_breaker_resets_on_success():
    """A successful search resets the failure counter and closes the circuit."""
    sp = _make_pipeline()

    for _ in range(sp._max_failures):
        sp._record_search_failure()
    assert sp._circuit_open()

    sp._record_search_success()

    assert not sp._circuit_open(), "Circuit must close after a successful search"
    assert sp._failure_count == 0


# ---------------------------------------------------------------------------
# 6. Cache hit bypasses network
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_execute_with_retry_cache_hit():
    """A cached result must be returned without any network call."""
    mock_tool = MagicMock()
    mock_tool.execute = AsyncMock()

    sp = _make_pipeline(search_tool=mock_tool)
    sp.cache.get.return_value = {"sources": _GOOD_RESULT}

    result = await sp.execute_with_retry("who won the match?")

    assert result == _GOOD_RESULT
    mock_tool.execute.assert_not_called()


# ---------------------------------------------------------------------------
# 7. needs_search() LLM timeout -> safe default False
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_needs_search_llm_timeout_returns_false():
    """If the LLM classification call times out, needs_search() returns False safely."""
    query = "tell me about recursion"

    sp = _make_pipeline()

    with patch("knowledge.search_pipeline.asyncio.wait_for", side_effect=asyncio.TimeoutError):
        result = await sp.needs_search(query)

    assert result is False, "LLM timeout in needs_search must default to False (no search)"


# ---------------------------------------------------------------------------
# 8. synthesize_answer() timeout -> canonical fallback
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_synthesize_answer_timeout_returns_canonical_fallback():
    """If synthesis LLM call times out, must return the canonical failure string."""
    mock_router = AsyncMock()
    sp = _make_pipeline(model_router=mock_router)

    with patch("knowledge.search_pipeline.asyncio.wait_for", side_effect=asyncio.TimeoutError):
        result = await sp.synthesize_answer("Who won the election?", _GOOD_RESULT)

    assert result["answer"] == _CANONICAL_FAILURE
    assert result["confidence"] == 0.0
    assert result["sources"] == []


# ---------------------------------------------------------------------------
# 9. synthesize_answer() with no sources -> canonical fallback
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_synthesize_answer_empty_sources():
    """Empty ranked_sources must immediately return the canonical failure string."""
    sp = _make_pipeline()
    result = await sp.synthesize_answer("What is the weather?", [])

    assert result["answer"] == _CANONICAL_FAILURE
    assert result["confidence"] == 0.0


# ---------------------------------------------------------------------------
# 10. Evidence extraction timeout -> raw snippet fallback
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_build_structured_evidence_timeout_uses_raw_snippets():
    """A timed-out evidence extraction LLM call must fall back to raw snippets."""
    mock_router = AsyncMock()
    sp = _make_pipeline(model_router=mock_router)

    with patch("knowledge.search_pipeline.asyncio.wait_for", side_effect=asyncio.TimeoutError):
        result = await sp.build_structured_evidence("GPU benchmarks", _GOOD_RESULT)

    assert len(result) > 0
    for s in result:
        assert "key_facts" in s, "Timed-out evidence extraction must populate key_facts"
        assert s["key_facts"]


# ---------------------------------------------------------------------------
# 11. Hallucination sentinel overwrites bad LLM output
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_synthesize_answer_strips_cutoff_phrases():
    """If LLM echoes cutoff/verify phrases, output must be overwritten with canonical string."""
    bad_phrases = [
        "My training cutoff is 2024 so I cannot answer.",
        "I couldn't verify this information from reliable sources.",
        "I cannot verify this claim.",
        "I tried but fabricate it I cannot.",
    ]

    for bad_phrase in bad_phrases:
        async def _fake_wait_for(coro, timeout, bad=bad_phrase):
            return bad

        mock_router = AsyncMock()
        sp = _make_pipeline(model_router=mock_router)
        with patch("knowledge.search_pipeline.asyncio.wait_for", side_effect=_fake_wait_for):
            result = await sp.synthesize_answer("recent AI news", _GOOD_RESULT)

        assert result["answer"] == _CANONICAL_FAILURE, (
            f"Phrase must be overwritten: {bad_phrase[:50]}"
        )


# ---------------------------------------------------------------------------
# 12. KnowledgeRouter rejects canonical failure string as a search hit
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_router_rejects_canonical_failure_answer_as_hit():
    """
    When synthesize_answer returns the canonical failure string with high
    confidence, the router must NOT treat it as a successful internet_search hit.
    The old stale check ('couldn't verify') would have allowed this through.
    """
    mock_router = AsyncMock()
    pool = MagicMock()

    with (
        patch("knowledge.router.ResearchCache") as MockCache,
        patch("knowledge.router.ProjectManager"),
        patch("knowledge.router.WebSearchTool"),
        patch("knowledge.router.SourceVerifier"),
    ):
        MockCache.return_value.get.return_value = None

        from knowledge.router import KnowledgeRouter
        router = KnowledgeRouter(pool, MagicMock(), MagicMock(), mock_router)

        router.search_pipeline = MagicMock()
        router.search_pipeline.execute_with_retry = AsyncMock(return_value=_GOOD_RESULT)
        router.search_pipeline.score_and_rank_sources = MagicMock(return_value=_GOOD_RESULT)
        router.search_pipeline.synthesize_answer = AsyncMock(return_value={
            "answer": _CANONICAL_FAILURE,
            "confidence": 0.85,
            "sources": _GOOD_RESULT,
        })

        result = await router.query_escalation("who won the election?")

    assert result["layer"] != "internet_search", (
        "Router must reject synthesis that returns the canonical failure string"
    )


# ---------------------------------------------------------------------------
# 13. KnowledgeRouter final fallback uses canonical string
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_router_final_fallback_uses_canonical_string():
    """When all layers fail, the router final return uses the canonical failure string."""
    pool = MagicMock()

    # memory_manager must be an AsyncMock because the router awaits retrieve()
    mock_mem_mgr = AsyncMock()
    mock_mem_mgr.retrieve = AsyncMock(return_value=[])

    with (
        patch("knowledge.router.ResearchCache") as MockCache,
        patch("knowledge.router.ProjectManager"),
        patch("knowledge.router.WebSearchTool"),
        patch("knowledge.router.SourceVerifier"),
    ):
        MockCache.return_value.get.return_value = None

        from knowledge.router import KnowledgeRouter
        router = KnowledgeRouter(pool, mock_mem_mgr, MagicMock(), MagicMock())

        router.search_pipeline = MagicMock()
        router.search_pipeline.execute_with_retry = AsyncMock(return_value=[])
        router.search_pipeline.score_and_rank_sources = MagicMock(return_value=[])
        router.search_pipeline.synthesize_answer = AsyncMock(return_value={
            "answer": _CANONICAL_FAILURE,
            "confidence": 0.0,
            "sources": [],
        })

        result = await router.query_escalation("some obscure query with no results")

    assert result["layer"] == "none"
    assert result["answer"] == _CANONICAL_FAILURE


# ---------------------------------------------------------------------------
# 14. ContextBuildStage: search exception never blocks model generation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_context_build_stage_search_exception_still_produces_prompt():
    """
    Even when search raises an exception, ContextBuildStage must complete and
    set context.full_prompt so model generation can proceed normally.
    """
    state = ConversationState(id="test_search_fail_prompt")
    intel = ContextIntelligenceEngine()
    stage = ContextBuildStage(intel)

    mock_app = MagicMock()
    mock_router = MagicMock()
    mock_router.query_escalation = AsyncMock(side_effect=RuntimeError("provider down"))
    mock_app.state.knowledge_router = mock_router

    mock_conv_engine = MagicMock()
    mock_conv_engine.app = mock_app
    stage.conversation_engine = mock_conv_engine

    with patch("knowledge.v2.integration.SearchIntegration.execute_search", side_effect=RuntimeError("provider down")):
        ctx = ConversationContext(state=state, user_message="What is the latest GPU?")
        await stage.process(ctx)

    assert ctx.full_prompt, "full_prompt must be set even when search raises"
    assert ctx.search_triggered is True
    assert ctx.search_succeeded is False
    assert ctx.search_failure_reason == "system_error"
    assert "[SEARCH SYSTEM ERROR]" in ctx.full_prompt


# ---------------------------------------------------------------------------
# 15. ContextBuildStage: circuit-breaker-open (no results) still produces prompt
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_context_build_stage_no_results_still_produces_prompt():
    """
    When search returns no results (same path as circuit breaker open),
    ContextBuildStage must still produce a complete, non-empty prompt.
    """
    state = ConversationState(id="test_no_results_prompt")
    intel = ContextIntelligenceEngine()
    stage = ContextBuildStage(intel)

    mock_app = MagicMock()
    mock_router = MagicMock()
    mock_router.query_escalation = AsyncMock(return_value={
        "answer": "",
        "layer": "none",
        "confidence": 0.0,
        "sources": [],
    })
    mock_app.state.knowledge_router = mock_router

    mock_conv_engine = MagicMock()
    mock_conv_engine.app = mock_app
    stage.conversation_engine = mock_conv_engine

    from knowledge.v2.models import SearchContext
    mock_dto = SearchContext(
        search_triggered=True,
        search_succeeded=False,
        query="Latest crypto prices",
        results_count=0,
        formatted_block="[SEARCH RETURNED NO RESULTS]",
        failure_reason="no_results"
    )

    with patch("knowledge.v2.integration.SearchIntegration.execute_search", new_callable=AsyncMock) as mock_exec:
        mock_exec.return_value = mock_dto
        ctx = ConversationContext(state=state, user_message="Latest crypto prices")
        await stage.process(ctx)

    assert ctx.full_prompt, "full_prompt must be non-empty even when no results returned"
    assert ctx.search_succeeded is False
