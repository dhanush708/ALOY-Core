from typing import Dict, Any, Protocol
from .base import ISubsystem

class IReasoningEngine(ISubsystem, Protocol):
    """Interface for the Reasoning Engine subsystem."""
    
    async def reason(self, query: str, context: Dict[str, Any], depth: str) -> Any:
        """Perform reasoning at a specified depth (simple, chain, deep)."""
        ...
