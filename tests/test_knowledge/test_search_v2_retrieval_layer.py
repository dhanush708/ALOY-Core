"""
Unit tests for ALOY Search V2 Retrieval Layer (knowledge/v2/retrieval_layer.py).
Target coverage: >90%. All tests use mock providers — zero internet dependency.
"""

import asyncio
import pytest
from typing import List, Dict, Any, Optional
from knowledge.v2.interfaces import ISearchProvider
from knowledge.v2.models import NormalizedResult
from knowledge.v2.providers.registry import ProviderRegistry
from knowledge.v2.retrieval_layer import RetrievalLayer


class MockProvider(ISearchProvider):
    """Mock search provider for unit testing."""

    def __init__(
        self,
        name: str,
        results: Optional[List[NormalizedResult]] = None,
        delay_seconds: float = 0.0,
        should_fail: bool = False,
        available: bool = True
    ):
        self._name = name
        self._results = results or [
            NormalizedResult(
                title=f"Result from {name}",
                url=f"https://{name}.com",
                snippet=f"Snippet from {name}",
                provider=name
            )
        ]
        self._delay = delay_seconds
        self._should_fail = should_fail
        self._available = available

    @property
    def name(self) -> str:
        return self._name

    @property
    def capabilities(self) -> List[str]:
        return ["web"]

    async def is_available(self) -> bool:
        return self._available

    async def execute(self, query: str, options: Optional[Dict[str, Any]] = None) -> List[NormalizedResult]:
        if self._delay > 0:
            await asyncio.sleep(self._delay)

        if self._should_fail:
            raise RuntimeError(f"Provider {self._name} simulated failure")

        return self._results


class TestRetrievalLayer:

    def test_invalid_registry_type_raises_error(self):
        with pytest.raises(TypeError):
            RetrievalLayer(registry="not_a_registry")  # type: ignore

    @pytest.mark.asyncio
    async def test_empty_query_returns_empty_list(self):
        registry = ProviderRegistry()
        layer = RetrievalLayer(registry)
        assert await layer.retrieve("") == []
        assert await layer.retrieve("   ") == []

    @pytest.mark.asyncio
    async def test_empty_registry_returns_empty_list(self):
        registry = ProviderRegistry()
        layer = RetrievalLayer(registry)
        results = await layer.retrieve("test query")
        assert results == []

    @pytest.mark.asyncio
    async def test_single_provider_execution(self):
        registry = ProviderRegistry()
        p1 = MockProvider("p1")
        registry.register(p1)

        layer = RetrievalLayer(registry)
        results = await layer.retrieve("python search")

        assert len(results) == 1
        assert results[0].title == "Result from p1"
        assert results[0].provider == "p1"

    @pytest.mark.asyncio
    async def test_multiple_providers_concurrent_execution(self):
        registry = ProviderRegistry()
        p1 = MockProvider("p1", delay_seconds=0.05)
        p2 = MockProvider("p2", delay_seconds=0.05)
        p3 = MockProvider("p3", delay_seconds=0.05)

        registry.register(p1)
        registry.register(p2)
        registry.register(p3)

        layer = RetrievalLayer(registry)
        results = await layer.retrieve("concurrent query")

        assert len(results) == 3
        providers_retrieved = {r.provider for r in results}
        assert providers_retrieved == {"p1", "p2", "p3"}

    @pytest.mark.asyncio
    async def test_disabled_and_unavailable_providers_filtered(self):
        registry = ProviderRegistry()
        p_enabled = MockProvider("enabled_p", available=True)
        p_disabled = MockProvider("disabled_p", available=True)
        p_unavailable = MockProvider("unavail_p", available=False)

        registry.register(p_enabled, enabled=True)
        registry.register(p_disabled, enabled=False)
        registry.register(p_unavailable, enabled=True)

        layer = RetrievalLayer(registry)
        results = await layer.retrieve("filter query")

        assert len(results) == 1
        assert results[0].provider == "enabled_p"

    @pytest.mark.asyncio
    async def test_per_provider_timeout_isolation(self):
        registry = ProviderRegistry()
        fast_p = MockProvider("fast", delay_seconds=0.01)
        slow_p = MockProvider("slow", delay_seconds=0.5)

        registry.register(fast_p)
        registry.register(slow_p)

        # Set per-provider timeout to 0.1s
        layer = RetrievalLayer(registry, per_provider_timeout_seconds=0.1)
        results = await layer.retrieve("timeout test")

        assert len(results) == 1
        assert results[0].provider == "fast"

    @pytest.mark.asyncio
    async def test_provider_exception_isolation(self):
        registry = ProviderRegistry()
        good_p = MockProvider("good", should_fail=False)
        bad_p = MockProvider("bad", should_fail=True)

        registry.register(good_p)
        registry.register(bad_p)

        layer = RetrievalLayer(registry)
        results = await layer.retrieve("exception test")

        assert len(results) == 1
        assert results[0].provider == "good"

    @pytest.mark.asyncio
    async def test_explicit_provider_names_selection(self):
        registry = ProviderRegistry()
        p1 = MockProvider("p1")
        p2 = MockProvider("p2")
        registry.register(p1)
        registry.register(p2)

        layer = RetrievalLayer(registry)
        results = await layer.retrieve("select test", provider_names=["p2"])

        assert len(results) == 1
        assert results[0].provider == "p2"

    @pytest.mark.asyncio
    async def test_global_timeout_and_task_cancellation(self):
        registry = ProviderRegistry()
        slow_p1 = MockProvider("slow1", delay_seconds=1.0)
        slow_p2 = MockProvider("slow2", delay_seconds=1.0)

        registry.register(slow_p1)
        registry.register(slow_p2)

        # Set global timeout to 0.1s
        layer = RetrievalLayer(
            registry,
            global_timeout_seconds=0.1,
            per_provider_timeout_seconds=5.0
        )
        results = await layer.retrieve("global timeout query")

        assert results == []

    @pytest.mark.asyncio
    async def test_duplicate_provider_protection(self):
        registry = ProviderRegistry()
        p1 = MockProvider("duplicate")
        registry.register(p1)

        layer = RetrievalLayer(registry)
        results = await layer.retrieve("dup test", provider_names=["duplicate", "DUPLICATE"])

        assert len(results) == 1
        assert results[0].provider == "duplicate"
