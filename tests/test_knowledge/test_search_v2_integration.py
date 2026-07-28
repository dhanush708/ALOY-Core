"""
Unit tests for ALOY Search V2 Integration Layer (knowledge/v2/integration.py).
Target coverage: >90%. Pure unit tests mocking V1 and V2 search pipelines.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock
from knowledge.v2.models import SearchContext, RankedEvidence
from knowledge.v2.integration import (
    SearchIntegration,
    set_v2_enabled,
    is_v2_enabled,
    get_global_v2_pipeline
)


class TestSearchIntegration:

    def setup_method(self):
        # Reset feature flag to default True before each test
        set_v2_enabled(True)

    def test_feature_flag_toggle(self):
        set_v2_enabled(True)
        assert is_v2_enabled() is True

        set_v2_enabled(False)
        assert is_v2_enabled() is False

    @pytest.mark.asyncio
    async def test_v2_path_invoked_when_enabled(self):
        set_v2_enabled(True)

        mock_v2 = MagicMock()
        mock_v2.execute = AsyncMock(return_value=SearchContext(
            search_triggered=True,
            search_succeeded=True,
            query="v2 test query",
            results_count=1,
            formatted_block="[V2 BLOCK]"
        ))

        mock_v1 = MagicMock()

        integration = SearchIntegration(v2_pipeline=mock_v2)
        ctx = await integration.execute_search("v2 test query", v1_pipeline=mock_v1)

        assert ctx.search_succeeded is True
        assert ctx.formatted_block == "[V2 BLOCK]"
        assert mock_v2.execute.call_count == 1
        # V1 should NOT be called when V2 succeeds
        assert mock_v1.needs_search.call_count == 0

    @pytest.mark.asyncio
    async def test_v1_path_invoked_when_v2_disabled(self):
        set_v2_enabled(False)

        mock_v2 = MagicMock()

        mock_v1 = MagicMock()
        mock_v1.needs_search = AsyncMock(return_value=True)
        mock_v1.execute_with_retry = AsyncMock(return_value=[{"title": "V1 Title", "url": "https://v1.com", "snippet": "V1 text", "score": 90.0}])
        mock_v1.score_and_rank_sources = MagicMock(return_value=[{"title": "V1 Title", "url": "https://v1.com", "snippet": "V1 text", "score": 90.0}])

        integration = SearchIntegration(v2_pipeline=mock_v2)
        ctx = await integration.execute_search("v1 query", v1_pipeline=mock_v1)

        assert ctx.search_succeeded is True
        assert mock_v2.execute.call_count == 0
        assert mock_v1.needs_search.call_count == 1
        assert "V1 Title" in ctx.formatted_block

    @pytest.mark.asyncio
    async def test_automatic_fallback_on_v2_system_error(self):
        set_v2_enabled(True)

        # V2 pipeline returns a system error SearchContext
        mock_v2 = MagicMock()
        mock_v2.execute = AsyncMock(return_value=SearchContext(
            search_triggered=True,
            search_succeeded=False,
            query="fallback query",
            failure_reason="system_error"
        ))

        mock_v1 = MagicMock()
        mock_v1.needs_search = AsyncMock(return_value=True)
        mock_v1.execute_with_retry = AsyncMock(return_value=[{"title": "Fallback Source", "url": "https://fb.com", "snippet": "FB", "score": 85.0}])
        mock_v1.score_and_rank_sources = MagicMock(return_value=[{"title": "Fallback Source", "url": "https://fb.com", "snippet": "FB", "score": 85.0}])

        integration = SearchIntegration(v2_pipeline=mock_v2)
        ctx = await integration.execute_search("fallback query", v1_pipeline=mock_v1)

        assert ctx.search_succeeded is True
        assert mock_v2.execute.call_count == 1
        assert mock_v1.needs_search.call_count == 1
        assert "Fallback Source" in ctx.formatted_block

    @pytest.mark.asyncio
    async def test_automatic_fallback_on_v2_exception(self):
        set_v2_enabled(True)

        # V2 pipeline raises an unexpected exception
        mock_v2 = MagicMock()
        mock_v2.execute = AsyncMock(side_effect=RuntimeError("V2 Exception Boom!"))

        mock_v1 = MagicMock()
        mock_v1.needs_search = AsyncMock(return_value=True)
        mock_v1.execute_with_retry = AsyncMock(return_value=[{"title": "Exception Fallback", "url": "https://ex.com", "snippet": "EX", "score": 80.0}])
        mock_v1.score_and_rank_sources = MagicMock(return_value=[{"title": "Exception Fallback", "url": "https://ex.com", "snippet": "EX", "score": 80.0}])

        integration = SearchIntegration(v2_pipeline=mock_v2)
        ctx = await integration.execute_search("exception fallback query", v1_pipeline=mock_v1)

        assert ctx.search_succeeded is True
        assert mock_v1.needs_search.call_count == 1
        assert "Exception Fallback" in ctx.formatted_block

    @pytest.mark.asyncio
    async def test_fallback_when_v1_pipeline_is_none(self):
        set_v2_enabled(False)

        integration = SearchIntegration()
        ctx = await integration.execute_search("no v1 query", v1_pipeline=None)

        assert ctx.search_triggered is False
        assert ctx.search_succeeded is False
        assert ctx.failure_reason == "v1_unavailable"

    def test_global_v2_pipeline_instance(self):
        p = get_global_v2_pipeline()
        assert p is not None
        assert p.registry is not None
