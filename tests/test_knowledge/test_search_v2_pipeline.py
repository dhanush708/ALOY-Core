"""
Unit tests for ALOY Search V2 Search Pipeline Orchestrator (knowledge/v2/search_pipeline.py).
Target coverage: >90%. Isolates all downstream modules using mocks to ensure zero network dependency.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from knowledge.v2.models import SearchContext, SearchIntent, QueryPlan, NormalizedResult, RankedEvidence
from knowledge.v2.providers.registry import ProviderRegistry
from knowledge.v2.providers.duckduckgo import DuckDuckGoProvider
from knowledge.v2.search_pipeline import SearchPipelineV2


class TestSearchPipelineV2:

    def test_invalid_registry_type_raises_error(self):
        with pytest.raises(TypeError):
            SearchPipelineV2(registry="not_a_registry")  # type: ignore

    @pytest.mark.asyncio
    async def test_search_skipped_flow(self):
        registry = ProviderRegistry()
        pipeline = SearchPipelineV2(registry)

        # Greeting query does not require search
        ctx = await pipeline.execute("hello how are you")

        assert ctx.search_triggered is False
        assert ctx.search_succeeded is False
        assert ctx.results_count == 0
        assert ctx.intent.requires_search is False
        assert ctx.formatted_block == ""

    @pytest.mark.asyncio
    async def test_followup_search_flow(self):
        registry = ProviderRegistry()
        pipeline = SearchPipelineV2(registry)

        # Short query with prior search succeeded -> followup
        ctx = await pipeline.execute(
            query="what was the score?",
            prior_search_succeeded=True,
            prior_search_query="Super Bowl 2026"
        )

        assert ctx.search_triggered is True
        assert ctx.search_succeeded is True
        assert ctx.intent.is_followup is True
        assert ctx.intent.intent_type == "followup"

    @pytest.mark.asyncio
    async def test_end_to_end_search_required_success_flow(self):
        registry = ProviderRegistry()

        # Mock retrieval layer to avoid network
        mock_retrieval = MagicMock()
        mock_retrieval.retrieve = AsyncMock(return_value=[
            NormalizedResult(
                title="Python 3.14 Official Release",
                url="https://docs.python.org/3.14/",
                snippet="Python 3.14 introduces JIT compiler optimizations.",
                provider="duckduckgo"
            )
        ])

        pipeline = SearchPipelineV2(registry=registry, retrieval_layer=mock_retrieval)

        ctx = await pipeline.execute("Python 3.14 release notes")

        assert ctx.search_triggered is True
        assert ctx.search_succeeded is True
        assert ctx.results_count == 1
        assert ctx.intent.requires_search is True
        assert ctx.plan is not None
        assert "[LIVE INTERNET SEARCH RESULTS]" in ctx.formatted_block
        assert "https://docs.python.org/3.14/" in ctx.formatted_block

    @pytest.mark.asyncio
    async def test_empty_retrieval_results_flow(self):
        registry = ProviderRegistry()

        mock_retrieval = MagicMock()
        mock_retrieval.retrieve = AsyncMock(return_value=[])

        pipeline = SearchPipelineV2(registry=registry, retrieval_layer=mock_retrieval)

        ctx = await pipeline.execute("query with no web results 2026")

        assert ctx.search_triggered is True
        assert ctx.search_succeeded is False
        assert ctx.results_count == 0
        assert "[SEARCH RETURNED NO RESULTS]" in ctx.formatted_block

    @pytest.mark.asyncio
    async def test_stage_exception_isolation(self):
        registry = ProviderRegistry()

        # Mock retrieval layer to throw exception
        mock_retrieval = MagicMock()
        mock_retrieval.retrieve = AsyncMock(side_effect=RuntimeError("Retrieval Layer Boom!"))

        pipeline = SearchPipelineV2(registry=registry, retrieval_layer=mock_retrieval)

        ctx = await pipeline.execute("latest news today")

        assert ctx.search_triggered is True
        assert ctx.search_succeeded is False
        assert ctx.failure_reason == "system_error"
        assert "[SEARCH SYSTEM ERROR]" in ctx.formatted_block

    @pytest.mark.asyncio
    async def test_multi_query_plan_execution(self):
        registry = ProviderRegistry()

        mock_retrieval = MagicMock()
        mock_retrieval.retrieve = AsyncMock(side_effect=[
            [NormalizedResult(title="Result A", url="https://a.com", snippet="A", provider="ddg")],
            [NormalizedResult(title="Result B", url="https://b.com", snippet="B", provider="ddg")],
            [NormalizedResult(title="Result C", url="https://c.com", snippet="C", provider="ddg")]
        ])

        pipeline = SearchPipelineV2(registry=registry, retrieval_layer=mock_retrieval)

        ctx = await pipeline.execute("Python vs Rust performance 2026")

        assert ctx.search_triggered is True
        assert ctx.search_succeeded is True
        assert ctx.plan.strategy == "multi_hop"
        # Retrieval was called 3 times (once per expanded query variant)
        assert mock_retrieval.retrieve.call_count == 3

    @pytest.mark.asyncio
    async def test_orchestration_overhead_benchmark(self):
        """Verify pipeline orchestration (excluding retrieval delay) runs in < 10ms."""
        registry = ProviderRegistry()

        mock_retrieval = MagicMock()
        mock_retrieval.retrieve = AsyncMock(return_value=[
            NormalizedResult(title="Fast Title", url="https://fast.org", snippet="Fast snippet", provider="ddg")
        ])

        pipeline = SearchPipelineV2(registry=registry, retrieval_layer=mock_retrieval)

        import time
        start = time.perf_counter()
        ctx = await pipeline.execute("benchmark latest news 2026")
        elapsed_ms = (time.perf_counter() - start) * 1000.0

        assert ctx.search_succeeded is True
        assert elapsed_ms < 10.0, f"Orchestration overhead was {elapsed_ms:.2f}ms (target < 10ms)"
