from dataclasses import dataclass, field
from typing import List, Optional, Any, AsyncGenerator

from .state import ConversationState
from .history import ConversationMessage
from memory.types import ScoredMemory

@dataclass
class ConversationContext:
    """Holds data passed through the conversation pipeline."""
    state: ConversationState
    user_message: str
    history: List[ConversationMessage] = field(default_factory=list)
    memories: List[ScoredMemory] = field(default_factory=list)
    
    system_prompt: str = ""
    full_prompt: str = ""
    
    intent: Optional[str] = None
    model: Optional[str] = None
    
    response_stream: Optional[AsyncGenerator[str, None]] = None
    final_response: str = ""
    event_queue: Optional[Any] = None
    
    # Store references to shared services if needed by stages
    services: dict = field(default_factory=dict)

class PipelineStage:
    """Base class for a stage in the conversation pipeline."""
    
    async def process(self, context: ConversationContext) -> ConversationContext:
        """Process the context and return it."""
        raise NotImplementedError
