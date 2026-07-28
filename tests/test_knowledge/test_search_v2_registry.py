"""
Unit tests for ALOY Search V2 Interfaces & Provider Registry (knowledge/v2/interfaces.py & registry.py).
Target coverage: >90%.
"""

import pytest
from typing import List, Dict, Any, Optional
from knowledge.v2.interfaces import ISearchProvider
from knowledge.v2.providers.registry import ProviderRegistry
from knowledge.v2.models import NormalizedResult


class DummyProvider(ISearchProvider):
    """Concrete test implementation of ISearchProvider."""

    def __init__(self, name: str = "dummy", capabilities: Optional[List[str]] = None, available: bool = True):
        self._name = name
        self._capabilities = capabilities or ["web"]
        self._available = available

    @property
    def name(self) -> str:
        return self._name

    @property
    def capabilities(self) -> List[str]:
        return self._capabilities

    async def is_available(self) -> bool:
        return self._available

    async def execute(self, query: str, options: Optional[Dict[str, Any]] = None) -> List[NormalizedResult]:
        return [
            NormalizedResult(
                title=f"Result for {query}",
                url="https://dummy.org",
                snippet="Dummy snippet",
                provider=self.name
            )
        ]


class InvalidProvider:
    """Class that does not inherit from ISearchProvider."""
    pass


class TestISearchProviderInterface:
    def test_abstract_interface_cannot_be_instantiated(self):
        with pytest.raises(TypeError):
            ISearchProvider()

    @pytest.mark.asyncio
    async def test_concrete_provider_contract(self):
        provider = DummyProvider(name="test_provider", capabilities=["web", "news"])
        assert provider.name == "test_provider"
        assert provider.capabilities == ["web", "news"]
        assert await provider.is_available() is True

        results = await provider.execute("test query")
        assert len(results) == 1
        assert results[0].title == "Result for test query"
        assert results[0].provider == "test_provider"


class TestProviderRegistry:
    def test_register_and_get_provider(self):
        registry = ProviderRegistry()
        p = DummyProvider(name="duckduckgo")
        registry.register(p)

        retrieved = registry.get("duckduckgo")
        assert retrieved is p
        assert registry.is_enabled("duckduckgo") is True

    def test_case_insensitive_lookup(self):
        registry = ProviderRegistry()
        p = DummyProvider(name="DuckDuckGo")
        registry.register(p)

        assert registry.get("DUCKDUCKGO") is p
        assert registry.get("duckduckgo") is p
        assert registry.is_enabled("dUcKdUcKgO") is True

    def test_register_invalid_type_raises_error(self):
        registry = ProviderRegistry()
        with pytest.raises(TypeError):
            registry.register(InvalidProvider())  # type: ignore

    def test_register_empty_name_raises_error(self):
        registry = ProviderRegistry()
        p = DummyProvider(name="   ")
        with pytest.raises(ValueError):
            registry.register(p)

    def test_duplicate_registration_raises_error(self):
        registry = ProviderRegistry()
        p1 = DummyProvider(name="google")
        p2 = DummyProvider(name="google")

        registry.register(p1)
        with pytest.raises(ValueError):
            registry.register(p2)

    def test_duplicate_registration_with_overwrite(self):
        registry = ProviderRegistry()
        p1 = DummyProvider(name="google", capabilities=["web"])
        p2 = DummyProvider(name="google", capabilities=["news"])

        registry.register(p1)
        registry.register(p2, overwrite=True)

        retrieved = registry.get("google")
        assert retrieved is p2
        assert retrieved.capabilities == ["news"]

    def test_unregister_provider(self):
        registry = ProviderRegistry()
        p = DummyProvider(name="bing")
        registry.register(p)

        unregistered = registry.unregister("bing")
        assert unregistered is p
        assert registry.get("bing") is None
        assert registry.is_enabled("bing") is False

        # Unregister non-existent
        assert registry.unregister("bing") is None

    def test_enable_disable_provider(self):
        registry = ProviderRegistry()
        p = DummyProvider(name="wiki")
        registry.register(p, enabled=True)

        assert registry.is_enabled("wiki") is True

        assert registry.set_enabled("wiki", False) is True
        assert registry.is_enabled("wiki") is False

        # Non-existent provider
        assert registry.set_enabled("non_existent", True) is False
        assert registry.is_enabled("non_existent") is False

    def test_list_all_and_list_enabled(self):
        registry = ProviderRegistry()
        p1 = DummyProvider(name="p1")
        p2 = DummyProvider(name="p2")
        p3 = DummyProvider(name="p3")

        registry.register(p1, enabled=True)
        registry.register(p2, enabled=False)
        registry.register(p3, enabled=True)

        all_providers = registry.list_all()
        assert len(all_providers) == 3
        assert p1 in all_providers
        assert p2 in all_providers
        assert p3 in all_providers

        enabled_providers = registry.list_enabled()
        assert len(enabled_providers) == 2
        assert p1 in enabled_providers
        assert p3 in enabled_providers
        assert p2 not in enabled_providers

    def test_clear_registry(self):
        registry = ProviderRegistry()
        registry.register(DummyProvider(name="p1"))
        registry.register(DummyProvider(name="p2"))

        assert len(registry.list_all()) == 2
        registry.clear()
        assert len(registry.list_all()) == 0
        assert registry.get("p1") is None
