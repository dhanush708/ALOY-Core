import logging
from typing import List

from .pipeline import PipelineStage, ConversationContext
from .state import ConversationState
from .history import ConversationStore
from .intent import IntentDetectionStage
from .context_builder import HistoryLoadStage, MemoryRetrievalStage, ContextBuildStage
from .response import ResponseGenerationStage
from memory.manager import MemoryManager
from .context_intelligence import ContextIntelligenceEngine

logger = logging.getLogger(__name__)

class ConversationEngine:
    """Orchestrates the conversation pipeline."""
    
    def __init__(self, db_pool, memory_manager: MemoryManager, model_router=None, identity_engine=None):
        self.db_pool = db_pool
        self.memory_manager = memory_manager
        self.model_router = model_router
        self.identity_engine = identity_engine
        self.history_store = ConversationStore(db_pool)
        self.intelligence_engine = ContextIntelligenceEngine()
        self.app = None  # Will be set by server lifespan
        
        # Build pipeline
        self.pipeline: List[PipelineStage] = [
            IntentDetectionStage(model_router=model_router),
            HistoryLoadStage(self.history_store, limit=10),
            MemoryRetrievalStage(memory_manager, limit=20),
            ContextBuildStage(self.intelligence_engine, identity_engine=identity_engine, conversation_engine=self),
            ResponseGenerationStage(model_router=model_router)
        ]
        
    async def get_or_create_state(self, conversation_id: str) -> ConversationState:
        """Get existing state or create a new one."""
        state = await self.history_store.get_conversation(conversation_id)
        if not state:
            state = await self.history_store.create_conversation(ConversationState(id=conversation_id))
        return state
        
    async def process_message(self, conversation_id: str, message: str, event_queue = None) -> ConversationContext:
        """Run a message through the pipeline."""
        state = await self.get_or_create_state(conversation_id)
        state.add_turn()
        
        # Save user message to history
        await self.history_store.add_message(
            conversation_id=conversation_id,
            role="user",
            content=message
        )
        
        # Generate title from first user message if not already set
        if not state.title or state.title == "Untitled Chat":
            words = message.split()
            title = " ".join(words[:5])
            if len(title) > 30:
                title = title[:27] + "..."
            state.title = title
            
        context = ConversationContext(state=state, user_message=message, event_queue=event_queue)
        
        for stage in self.pipeline:
            context = await stage.process(context)
            
        # Update state in DB
        await self.history_store.update_conversation(context.state)
        
        return context
        
    async def save_assistant_response(self, conversation_id: str, content: str):
        """Save the final assistant response after streaming completes."""
        await self.history_store.add_message(
            conversation_id=conversation_id,
            role="assistant",
            content=content
        )
