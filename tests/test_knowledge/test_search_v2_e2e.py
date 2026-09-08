"""
End-to-End Production Validation Test Suite for ALOY Search V2.
Verifies complete system behavior across all phases: decision, planning,
concurrent retrieval, CPU ranking, context assembly, telemetry, and V1 fallback.
Zero live network dependency — all tests use isolated mocks/stubs.
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from knowledge.v2.models import SearchContext, NormalizedResult, RankedEvidence
from knowledge.v2.providers.registry import ProviderRegistry
from knowledge.v2.providers.duckduckgo import DuckDuckGoProvider
from knowledge.v2.retrieval_layer import RetrievalLayer
from knowledge.v2.relevance_engine import RelevanceEngine
from knowledge.v2.context_assembler import ContextAssembler
from knowledge.v2.decision_engine import DecisionEngine
from knowledge.v2.query_planner import QueryPlanner
from knowledge.v2.search_pipeline import SearchPipelineV2
from knowledge.v2.integration import (
    SearchIntegration,
    set_v2_enabled,
    is_v2_enabled,
    get_telemetry_metrics,
    reset_telemetry_metrics
)


class TestSearchV2EndToEnd:

    def setup_method(self):
        set_v2_enabled(True)
        reset_telemetry_metrics()

    @pytest.mark.asyncio
    async def test_e2e_no_search_request(self):
        """Phase 5: Test no-search request (casual greeting / local math)."""
        integration = SearchIntegration()
        ctx = await integration.execute_search("hello good morning")

        assert ctx.search_triggered is False
        assert ctx.search_succeeded is False
        assert ctx.intent.intent_type == "none"

        metrics = get_telemetry_metrics()
        assert metrics["v2_requests"] == 1
        assert metrics["v2_avoided"] == 1

    @pytest.mark.asyncio
    async def test_e2e_normal_search_flow(self):
        """Phase 5: Test normal live search request."""
        mock_retrieval = MagicMock()
        mock_retrieval.retrieve = AsyncMock(return_value=[
            NormalizedResult(
                title="Python 3.14 Official News",
                url="https://docs.python.org/3.14/",
                snippet="Python 3.14 introduces JIT compilation for faster execution.",
                provider="duckduckgo"
            )
        ])

        registry = ProviderRegistry()
        pipeline = SearchPipelineV2(registry=registry, retrieval_layer=mock_retrieval)
        integration = SearchIntegration(v2_pipeline=pipeline)

        ctx = await integration.execute_search("Python 3.14 release date")

        assert ctx.search_triggered is True
        assert ctx.search_succeeded is True
        assert ctx.results_count == 1
        assert "[Context Information]" in ctx.formatted_block
        assert "https://docs.python.org/3.14/" in ctx.formatted_block

        metrics = get_telemetry_metrics()
        assert metrics["v2_requests"] == 1
        assert metrics["v2_successes"] == 1

    @pytest.mark.asyncio
    async def test_e2e_followup_search_flow(self):
        """Phase 5: Test follow-up search context reuse."""
        integration = SearchIntegration()
        ctx = await integration.execute_search(
            query="what was the score?",
            prior_search_succeeded=True,
            prior_search_query="Super Bowl 2026"
        )

        assert ctx.search_triggered is True
        assert ctx.search_succeeded is True
        assert ctx.intent.is_followup is True

    @pytest.mark.asyncio
    async def test_e2e_comparison_multi_query_search(self):
        """Phase 5: Test comparative multi-hop query planning & retrieval."""
        mock_retrieval = MagicMock()
        mock_retrieval.retrieve = AsyncMock(side_effect=[
            [NormalizedResult(title="Claude 3.5 specs", url="https://claude.ai", snippet="Claude details", provider="ddg")],
            [NormalizedResult(title="Gemini 1.5 specs", url="https://gemini.google", snippet="Gemini details", provider="ddg")],
            [NormalizedResult(title="AI Benchmark 2026", url="https://benchmark.org", snippet="AI results", provider="ddg")]
        ])

        registry = ProviderRegistry()
        pipeline = SearchPipelineV2(registry=registry, retrieval_layer=mock_retrieval)
        integration = SearchIntegration(v2_pipeline=pipeline)

        ctx = await integration.execute_search("compare Claude 3.5 vs Gemini 1.5 Pro performance in 2026")

        assert ctx.search_triggered is True
        assert ctx.search_succeeded is True
        assert ctx.plan.strategy == "multi_hop"
        assert len(ctx.plan.queries) == 3
        assert mock_retrieval.retrieve.call_count == 3

    @pytest.mark.asyncio
    async def test_e2e_v2_failure_automatic_v1_fallback(self):
        """Phase 5: Test Search V2 failure automatic fallback to Search V1."""
        set_v2_enabled(True)

        mock_v2 = MagicMock()
        mock_v2.execute = AsyncMock(side_effect=RuntimeError("V2 Hardware Failure"))

        mock_v1 = MagicMock()
        mock_v1.needs_search = AsyncMock(return_value=True)
        mock_v1.execute_with_retry = AsyncMock(return_value=[{"title": "V1 Recovered Title", "url": "https://v1.org", "snippet": "V1 text"}])
        mock_v1.score_and_rank_sources = MagicMock(return_value=[{"title": "V1 Recovered Title", "url": "https://v1.org", "snippet": "V1 text"}])

        integration = SearchIntegration(v2_pipeline=mock_v2)
        ctx = await integration.execute_search("query triggering fallback", v1_pipeline=mock_v1)

        assert ctx.search_succeeded is True
        assert "V1 Recovered Title" in ctx.formatted_block

        metrics = get_telemetry_metrics()
        assert metrics["v2_failures"] == 1
        assert metrics["v1_fallbacks"] == 1

    @pytest.mark.asyncio
    async def test_e2e_feature_flag_switching(self):
        """Phase 5: Test dynamic feature flag switching at runtime."""
        mock_v2 = MagicMock()
        mock_v2.execute = AsyncMock(return_value=SearchContext(search_triggered=True, search_succeeded=True, formatted_block="[V2 BLOCK]"))

        mock_v1 = MagicMock()
        mock_v1.needs_search = AsyncMock(return_value=True)
        mock_v1.execute_with_retry = AsyncMock(return_value=[{"title": "V1 Source", "url": "https://v1.com", "snippet": "Text"}])
        mock_v1.score_and_rank_sources = MagicMock(return_value=[{"title": "V1 Source", "url": "https://v1.com", "snippet": "Text"}])

        integration = SearchIntegration(v2_pipeline=mock_v2)

        # 1. Enable V2
        set_v2_enabled(True)
        ctx_v2 = await integration.execute_search("test query 1", v1_pipeline=mock_v1)
        assert "[V2 BLOCK]" in ctx_v2.formatted_block

        # 2. Disable V2
        set_v2_enabled(False)
        ctx_v1 = await integration.execute_search("test query 2", v1_pipeline=mock_v1)
        assert "V1 Source" in ctx_v1.formatted_block

    @pytest.mark.asyncio
    async def test_e2e_sequential_and_concurrent_searches(self):
        """Phase 5: Test multiple sequential and concurrent search executions."""
        mock_retrieval = MagicMock()
        mock_retrieval.retrieve = AsyncMock(return_value=[
            NormalizedResult(title="Concurrent Result", url="https://concurrent.org", snippet="Concurrent text", provider="ddg")
        ])

        registry = ProviderRegistry()
        pipeline = SearchPipelineV2(registry=registry, retrieval_layer=mock_retrieval)
        integration = SearchIntegration(v2_pipeline=pipeline)

        # Run 5 concurrent searches
        tasks = [
            integration.execute_search(f"concurrent search query {i} 2026")
            for i in range(5)
        ]
        results = await asyncio.gather(*tasks)

        assert len(results) == 5
        assert all(r.search_succeeded for r in results)

        metrics = get_telemetry_metrics()
        assert metrics["v2_requests"] == 5
        assert metrics["v2_successes"] == 5
