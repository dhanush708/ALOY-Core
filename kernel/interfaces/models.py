from typing import AsyncIterator, Any, Protocol
from .base import ISubsystem

class IModelRouter(ISubsystem, Protocol):
    """Interface for the Model Router subsystem."""
    
    async def route(self, task: str, complexity: str) -> Any:
        """Determine the best model for a given task and complexity."""
        ...
        
    async def generate(self, prompt: str, task: str, **kwargs: Any) -> str:
        """Generate a complete text response."""
        ...
        
    async def generate_stream(self, prompt: str, task: str, **kwargs: Any) -> AsyncIterator[str]:
        """Generate a streaming text response."""
        ...
