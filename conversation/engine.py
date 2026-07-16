import logging
from typing import List, Optional, Dict

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
        
    async def save_assistant_response(self, conversation_id: str, content: str, metadata: Optional[dict] = None):
        """Save the final assistant response after streaming completes."""
        await self.history_store.add_message(
            conversation_id=conversation_id,
            role="assistant",
            content=content,
            metadata=metadata
        )
        try:
            await self.compact_conversation_if_needed(conversation_id)
        except Exception as e:
            logger.error(f"Failed to compact conversation {conversation_id}: {e}", exc_info=True)

    async def compact_conversation_if_needed(self, conversation_id: str) -> None:
        """Check if history size exceeds threshold and run auto-summarization, context compression,
        memory extraction, and history pruning."""
        # 1. Fetch conversation state
        state = await self.history_store.get_conversation(conversation_id)
        if not state:
            return
            
        # 2. Get history list
        history = await self.history_store.get_history(conversation_id, limit=100)
        
        # We compact if we have more than 12 messages in history
        if len(history) < 12:
            return
            
        logger.info(f"Compaction triggered for conversation {conversation_id} (history size: {len(history)})")
        
        # Keep the most recent 4 messages intact
        to_summarize = history[:-4]
        to_keep = history[-4:]
        
        if len(to_summarize) < 4:
            return
            
        # 3. Generate summary of the older messages
        summary_prompt = (
            "Summarize the following conversation history concisely in 3-5 bullet points, "
            "capturing all key decisions, facts, user preferences, and open questions:\n\n"
            + "\n".join(f"{m.role.capitalize()}: {m.content}" for m in to_summarize)
        )
        
        summary_text = ""
        if self.model_router:
            try:
                summary_text = await self.model_router.generate("summarization", summary_prompt)
            except Exception as e:
                logger.error(f"Failed to generate history summary: {e}")
                
        # 4. Extract long-term facts/memories from the older messages
        if self.memory_manager and self.model_router:
            extraction_prompt = (
                "Extract key facts, user preferences, or project details from the following conversation history "
                "that should be saved as persistent memories. Return them as a list of short, declarative facts "
                "(one per line), or return nothing if there are no new facts to save:\n\n"
                + "\n".join(f"{m.role.capitalize()}: {m.content}" for m in to_summarize)
            )
            try:
                extracted_text = await self.model_router.generate("reflection", extraction_prompt)
                for line in extracted_text.split("\n"):
                    line = line.strip().strip("-").strip("*").strip()
                    if line and len(line) > 10 and not any(kw in line.lower() for kw in ("no new facts", "no facts", "nothing to")):
                        await self.memory_manager.store(
                            type="conversation_memory",
                            content=line,
                            tier="short_term",
                            importance=0.6,
                            metadata={"source_conversation_id": conversation_id}
                        )
                        logger.info(f"Extracted memory: {line}")
            except Exception as e:
                logger.error(f"Failed to extract memories during compaction: {e}")
                
        # 5. Prune history and insert summary
        to_summarize_ids = [m.id for m in to_summarize]
        with self.db_pool.get_write_connection() as conn:
            # Delete older messages
            placeholders = ",".join("?" * len(to_summarize_ids))
            conn.execute(
                f"DELETE FROM conversation_messages WHERE id IN ({placeholders})",
                to_summarize_ids
            )
            
        # Insert the summary as a special system message
        from datetime import timedelta
        summary_time = to_keep[0].created_at - timedelta(seconds=1)
        summary_content = f"Summary of past conversation:\n{summary_text}"
        await self.history_store.add_message(
            conversation_id=conversation_id,
            role="system",
            content=summary_content,
            metadata={"is_summary": True},
            created_at=summary_time
        )
        
        # 6. Update FSM state turn count
        state.turn_count = len(to_keep) + 1
        await self.history_store.update_conversation(state)
        logger.info(f"Compaction completed successfully for conversation {conversation_id}.")
