from typing import List, Any, Protocol
from .base import ISubsystem

class ILearningEngine(ISubsystem, Protocol):
    """Interface for the Learning Engine subsystem."""
    
    async def process_conversation(self, conversation_id: str) -> List[Any]:
        """Extract observations from a completed conversation."""
        ...
        
    async def reflect(self) -> List[Any]:
        """Perform self-reflection and insight generation."""
        ...
