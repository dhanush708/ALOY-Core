from typing import List, Dict, Any, Optional, Protocol
from .base import ISubsystem

class IMemoryManager(ISubsystem, Protocol):
    """Interface for the Memory Management subsystem."""
    
    async def store(self, memory_type: str, content: str, **kwargs: Any) -> Any:
        """Store a new memory."""
        ...
        
    async def retrieve(self, query: str, types: Optional[List[str]] = None, limit: int = 10, **kwargs: Any) -> List[Any]:
        """Retrieve memories based on a query."""
        ...
        
    async def update(self, memory_id: str, **kwargs: Any) -> Any:
        """Update an existing memory."""
        ...
        
    async def delete(self, memory_id: str, force: bool = False) -> bool:
        """Delete a memory."""
        ...
