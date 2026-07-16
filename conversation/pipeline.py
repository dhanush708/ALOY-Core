from dataclasses import dataclass, field
from typing import List, Optional, Any, AsyncGenerator, Dict

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

    # ── Live Search State ─────────────────────────────────────────────────
    # Set by ContextBuildStage; consumed by ResponseGenerationStage and streaming.py
    search_triggered: bool = False        # True if a live search was attempted this turn
    search_succeeded: bool = False        # True if valid results were retrieved
    search_confidence: float = 0.0       # Confidence score returned by verifier/router
    search_result_count: int = 0         # Number of deduplicated result snippets
    search_sources: List[Dict] = field(default_factory=list)  # [{title, url, snippet}]
    search_timestamp: str = ""           # UTC timestamp string of when search ran


class PipelineStage:
    """Base class for a stage in the conversation pipeline."""
    
    async def process(self, context: ConversationContext) -> ConversationContext:
        """Process the context and return it."""
        raise NotImplementedError
