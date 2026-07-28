"""
ALOY Search V2 — Retrieval Layer

Coordinates parallel execution of enabled search providers via ProviderRegistry.
Handles provider selection, concurrency, timeout isolation, exception safety,
and result aggregation.
"""

import asyncio
import logging
from typing import List, Dict, Any, Optional

from knowledge.v2.interfaces import ISearchProvider
from knowledge.v2.models import NormalizedResult
from knowledge.v2.providers.registry import ProviderRegistry

logger = logging.getLogger(__name__)


class RetrievalLayer:
    """I/O-bound engine that executes search queries concurrently across providers."""

    def __init__(
        self,
        registry: ProviderRegistry,
        global_timeout_seconds: float = 8.0,
        per_provider_timeout_seconds: float = 6.0
    ):
        if not isinstance(registry, ProviderRegistry):
            raise TypeError(f"registry must be an instance of ProviderRegistry, got {type(registry)}")

        self.registry = registry
        self.global_timeout = global_timeout_seconds
        self.per_provider_timeout = per_provider_timeout_seconds

    async def retrieve(
        self,
        query: str,
        provider_names: Optional[List[str]] = None,
        options: Optional[Dict[str, Any]] = None
    ) -> List[NormalizedResult]:
        """Execute a search query concurrently across target providers and return aggregated results."""
        if not query or not query.strip():
            return []

        target_providers = await self._select_providers(provider_names)
        if not target_providers:
            logger.info(f"RetrievalLayer: No available enabled providers for query '{query}'")
            return []

        options = options or {}

        # Launch concurrent tasks for all selected providers
        tasks = [
            asyncio.create_task(self._safe_execute_provider(p, query, options))
            for p in target_providers
        ]

        results: List[NormalizedResult] = []

        try:
            # Enforce global retrieval timeout
            responses = await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=self.global_timeout
            )

            for resp in responses:
                if isinstance(resp, list):
                    results.extend(resp)
                elif isinstance(resp, Exception):
                    logger.error(f"RetrievalLayer: Provider task raised unexpected exception: {resp}")

        except asyncio.TimeoutError:
            logger.warning(
                f"RetrievalLayer: Global retrieval timed out after {self.global_timeout}s for query '{query}'"
            )
            # Cancel any unfinished provider tasks
            for t in tasks:
                if not t.done():
                    t.cancel()

            # Collect completed tasks
            for t in tasks:
                if t.done() and not t.cancelled() and not t.exception():
                    results.extend(t.result())

        return results

    async def _select_providers(self, provider_names: Optional[List[str]] = None) -> List[ISearchProvider]:
        """Select, deduplicate, and verify operational status of target providers."""
        candidates: List[ISearchProvider] = []

        if provider_names is not None:
            seen_names = set()
            for name in provider_names:
                clean_name = name.strip().lower() if name else ""
                if clean_name and clean_name not in seen_names:
                    seen_names.add(clean_name)
                    if self.registry.is_enabled(clean_name):
                        p = self.registry.get(clean_name)
                        if p:
                            candidates.append(p)
        else:
            candidates = self.registry.list_enabled()

        # Deduplicate provider instances by name
        unique_candidates: List[ISearchProvider] = []
        seen = set()
        for p in candidates:
            if p.name not in seen:
                seen.add(p.name)
                unique_candidates.append(p)

        # Filter out unavailable providers
        available_providers: List[ISearchProvider] = []
        for p in unique_candidates:
            try:
                if await p.is_available():
                    available_providers.append(p)
                else:
                    logger.info(f"RetrievalLayer: Provider '{p.name}' is currently unavailable.")
            except Exception as e:
                logger.warning(f"RetrievalLayer: Provider '{p.name}' availability check failed: {e}")

        return available_providers

    async def _safe_execute_provider(
        self,
        provider: ISearchProvider,
        query: str,
        options: Dict[str, Any]
    ) -> List[NormalizedResult]:
        """Execute a single provider within per-provider timeout bounds and exception isolation."""
        try:
            res = await asyncio.wait_for(
                provider.execute(query, options),
                timeout=self.per_provider_timeout
            )
            if isinstance(res, list):
                return [item for item in res if isinstance(item, NormalizedResult)]
            return []
        except asyncio.TimeoutError:
            logger.warning(
                f"RetrievalLayer: Provider '{provider.name}' timed out after {self.per_provider_timeout}s"
            )
            return []
        except Exception as e:
            logger.error(f"RetrievalLayer: Provider '{provider.name}' execution failed: {e}")
            return []
