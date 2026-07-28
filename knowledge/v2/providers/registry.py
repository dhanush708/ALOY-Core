"""
ALOY Search V2 — Provider Registry

Lifecycle management for search provider instances. Responsible only for
registration, lookup, enumeration, and availability status tracking.
"""

import logging
from typing import Dict, List, Optional
from knowledge.v2.interfaces import ISearchProvider

logger = logging.getLogger(__name__)


class ProviderRegistry:
    """Registry managing search provider instances and their enablement status."""

    def __init__(self):
        self._providers: Dict[str, ISearchProvider] = {}
        self._enabled_states: Dict[str, bool] = {}

    def register(self, provider: ISearchProvider, enabled: bool = True, overwrite: bool = False) -> None:
        """Register a search provider instance.

        Raises:
            TypeError: If provider does not implement ISearchProvider.
            ValueError: If name is empty or provider already exists and overwrite is False.
        """
        if not isinstance(provider, ISearchProvider):
            raise TypeError(f"Provider must implement ISearchProvider, got {type(provider)}")

        name = provider.name.strip().lower() if provider.name else ""
        if not name:
            raise ValueError("Provider name cannot be empty.")

        if name in self._providers and not overwrite:
            raise ValueError(f"Provider '{name}' is already registered. Use overwrite=True to replace.")

        self._providers[name] = provider
        self._enabled_states[name] = enabled
        logger.info(f"ProviderRegistry: Registered provider '{name}' (enabled={enabled})")

    def unregister(self, name: str) -> Optional[ISearchProvider]:
        """Remove a provider from the registry by name."""
        key = name.strip().lower()
        provider = self._providers.pop(key, None)
        self._enabled_states.pop(key, None)
        if provider:
            logger.info(f"ProviderRegistry: Unregistered provider '{key}'")
        return provider

    def get(self, name: str) -> Optional[ISearchProvider]:
        """Lookup a registered provider by name."""
        return self._providers.get(name.strip().lower())

    def set_enabled(self, name: str, enabled: bool) -> bool:
        """Enable or disable a registered provider. Returns True if updated."""
        key = name.strip().lower()
        if key in self._providers:
            self._enabled_states[key] = enabled
            return True
        return False

    def is_enabled(self, name: str) -> bool:
        """Check if a provider is currently enabled."""
        key = name.strip().lower()
        return self._enabled_states.get(key, False)

    def list_all(self) -> List[ISearchProvider]:
        """Return a list of all registered provider instances."""
        return list(self._providers.values())

    def list_enabled(self) -> List[ISearchProvider]:
        """Return a list of all currently enabled provider instances."""
        return [
            provider for name, provider in self._providers.items()
            if self._enabled_states.get(name, False)
        ]

    def clear(self) -> None:
        """Remove all providers from the registry."""
        self._providers.clear()
        self._enabled_states.clear()
        logger.info("ProviderRegistry: Cleared all registered providers.")
