"""
ALOY Search V2 — Abstract Provider Interfaces

Defines the stable abstraction contract that all search providers must implement.
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from knowledge.v2.models import NormalizedResult


class ISearchProvider(ABC):
    """Abstract Base Class for all ALOY Search V2 Providers."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique identifier for the provider (e.g. 'duckduckgo', 'local_docs')."""
        pass

    @property
    @abstractmethod
    def capabilities(self) -> List[str]:
        """Supported search capabilities (e.g. ['web', 'news', 'technical_docs'])."""
        pass

    @abstractmethod
    async def is_available(self) -> bool:
        """Check if provider is available and operational."""
        pass

    @abstractmethod
    async def execute(
        self,
        query: str,
        options: Optional[Dict[str, Any]] = None
    ) -> List[NormalizedResult]:
        """Execute a search query and return normalized results."""
        pass
