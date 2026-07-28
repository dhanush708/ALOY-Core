import logging
from typing import List, Optional, Dict
import asyncio
import re

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
        self._background_tasks = set()
        
        # Build pipeline
        self.pipeline: List[PipelineStage] = [
            IntentDetectionStage(model_router=model_router),
            HistoryLoadStage(self.history_store, limit=40),
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
        
    async def process_message(self, conversation_id: str, message: str, event_queue = None, override: Optional[str] = None) -> ConversationContext:
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
            
        context = ConversationContext(state=state, user_message=message, event_queue=event_queue, model_override=override)
        
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
            
        # Spawn async memory evaluation (sieve pipeline) with tracking
        task = asyncio.create_task(self._async_memory_evaluation(conversation_id))
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

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
        summary_succeeded = False
        if self.model_router:
            try:
                summary_text = await self.model_router.generate("summarization", summary_prompt)
                if summary_text and len(summary_text.strip()) > 20:
                    summary_succeeded = True
                    logger.info(f"Compaction summary generated ({len(summary_text)} chars)")
                else:
                    logger.warning("Compaction summary was empty or too short — skipping deletion")
            except Exception as e:
                logger.error(f"Failed to generate history summary: {e}")

        # 4. Only prune if summary succeeded — NEVER delete without a valid replacement
        if not summary_succeeded:
            logger.warning(
                f"Compaction ABORTED for conversation {conversation_id}: "
                "summary generation failed. History preserved intact."
            )
            return

        # 5. Extraction is now handled asynchronously by the sieve pipeline, decoupled from compaction.

        # 6. Consolidate summaries: delete ALL previous summary messages before inserting new one
        with self.db_pool.get_write_connection() as conn:
            conn.execute(
                "DELETE FROM conversation_messages WHERE conversation_id = ? AND role = 'system' AND json_extract(metadata, '$.is_summary') = 1",
                (conversation_id,)
            )

        # 7. Prune history (delete the messages we summarized)
        to_summarize_ids = [m.id for m in to_summarize]
        with self.db_pool.get_write_connection() as conn:
            placeholders = ",".join("?" * len(to_summarize_ids))
            conn.execute(
                f"DELETE FROM conversation_messages WHERE id IN ({placeholders})",
                to_summarize_ids
            )

        # 8. Insert the consolidated summary as a single system message
        from datetime import timedelta
        summary_time = to_keep[0].created_at - timedelta(seconds=1)
        summary_content = f"Summary of past conversation (messages 1–{len(to_summarize)}):\n{summary_text}"
        await self.history_store.add_message(
            conversation_id=conversation_id,
            role="system",
            content=summary_content,
            metadata={"is_summary": True, "compaction_index": state.turn_count},
            created_at=summary_time
        )

        # 9. Update turn count WITHOUT resetting — compaction should not affect greeting logic
        # turn_count reflects the TOTAL conversation turns, not messages in DB
        # We store the compaction point separately so identity engine still sees the real count
        await self.history_store.update_conversation(state)
        logger.info(
            f"Compaction completed for conversation {conversation_id}: "
            f"compacted {len(to_summarize)} messages into summary, "
            f"keeping {len(to_keep)} recent messages. turn_count={state.turn_count}"
        )

    async def _async_memory_evaluation(self, conversation_id: str):
        """Asynchronously evaluate the latest user message to see if it contains a stable long-term fact."""
        if not self.memory_manager or not self.model_router:
            return
            
        try:
            # Fetch the most recent user message
            history = await self.history_store.get_history(conversation_id, limit=2)
            user_msg = next((m.content for m in reversed(history) if m.role == "user"), None)
            if not user_msg:
                return

            # Deterministic Pre-filter: Ignore obvious non-memory chatter
            if not re.search(r'\b(i|my|mine|me|we|our|prefer|hate|love|always|never)\b', user_msg, re.IGNORECASE):
                logger.debug("Memory Sieve: Message rejected by heuristic pre-filter.")
                return

            # Sieve Prompt - binary classifier
            sieve_prompt = (
                "Evaluate if the following user message contains a permanent, long-term personal fact "
                "(e.g., name, allergies, goals, preferences, skills, dream company). "
                "Ignore temporary context, greetings, tasks, questions, or ephemeral conversation. "
                "Answer ONLY YES or NO.\n\n"
                f"Message: {user_msg}"
            )
            
            # Using the fast classifier model for low latency/cost
            from models.config import MODELS_CONFIG
            classifier_model = MODELS_CONFIG.get("vision", {}).get("name", "qwen2.5-coder:1.5b")
            
            response = await self.model_router.generate(
                task="classification",
                prompt=sieve_prompt,
                options={"temperature": 0.0},
            )
            
            if "YES" in response.upper():
                logger.info(f"Memory Sieve: Fact detected in conversation {conversation_id}. Triggering deep extraction.")
                await self._async_extract_and_store(conversation_id, user_msg)
            else:
                logger.debug(f"Memory Sieve: No fact detected.")
        except Exception as e:
            logger.error(f"Failed async memory evaluation: {e}")

    async def _async_extract_and_store(self, conversation_id: str, user_message: str):
        """Run deep extraction on a single message and store it, handling duplicates."""
        extraction_prompt = (
            "Extract key facts, user preferences, or project details from the following message "
            "that should be saved as persistent memories. Return them as a list of short, declarative facts "
            "(one per line), or return nothing if there are no new facts to save.\n\n"
            "CRITICAL INSTRUCTION 1: Always write facts about the user in the third person (e.g., 'The user prefers...', 'The user's dream company is...'). "
            "NEVER use 'I', 'me', or 'my' to refer to the user.\n"
            "CRITICAL INSTRUCTION 2: Do NOT extract current tasks, commands, debugging context, or temporary goals.\n\n"
            f"User: {user_message}"
        )
        try:
            extracted_text = await self.model_router.generate("reflection", extraction_prompt)
            for line in extracted_text.split("\n"):
                line = line.strip().strip("-").strip("*").strip()
                if line and len(line) > 10 and not any(kw in line.lower() for kw in ("no new facts", "no facts", "nothing to")):
                    # Check for duplicates before storing
                    await self._merge_or_store_fact(conversation_id, line)
        except Exception as e:
            logger.error(f"Failed to extract memory: {e}")

    async def _merge_or_store_fact(self, conversation_id: str, new_fact: str):
        """Check for existing similar facts and either merge/overwrite or insert new."""
        # Simple similarity check
        try:
            # We need to query retrieval engine for this user fact
            from memory.vector_store import VectorStore
            from memory.embeddings import EmbeddingEngine
            
            embedding_engine = EmbeddingEngine()
            vec_store = VectorStore(self.db_pool)
            
            vector = await embedding_engine.generate(new_fact)
            # Find the most similar existing memory
            results = vec_store.search(vector, limit=1)
            
            # If we find a highly similar fact (> 0.85), directly overwrite it (deterministic update)
            if results and results[0].get("score", 0) > 0.85:
                existing_id = results[0]["id"]
                existing_content = results[0]["content"]
                
                logger.info(f"Overwriting memory: '{existing_content}' -> '{new_fact}'")
                
                with self.db_pool.get_write_connection() as conn:
                    conn.execute(
                        "UPDATE memories SET content = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                        (new_fact, existing_id)
                    )
                logger.info(f"Merged memory saved: {new_fact}")
            else:
                # No highly similar fact, store as new
                await self.memory_manager.store(
                    type="conversation_memory",
                    content=new_fact,
                    tier="short_term",
                    importance=0.6,
                    metadata={"source_conversation_id": conversation_id}
                )
                logger.info(f"Extracted new memory: {new_fact}")
        except Exception as e:
            logger.error(f"Error during memory deduplication: {e}")
