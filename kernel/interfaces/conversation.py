from typing import AsyncIterator, List, Dict, Any, Protocol
from .base import ISubsystem

class IConversationEngine(ISubsystem, Protocol):
    """Interface for the Conversation Engine subsystem."""
    
    async def process_message(self, message: str, conversation_id: str) -> AsyncIterator[str]:
        """Process a user message and stream the response."""
        ...
        
    async def get_history(self, conversation_id: str, limit: int) -> List[Dict[str, Any]]:
        """Retrieve conversation history."""
        ...
