import logging
import asyncio
from typing import List, Dict, Any
from .pipeline import LearningContext, LearningPipelineStage

logger = logging.getLogger(__name__)

class LearningEngine:
    """Orchestrates the background learning pipeline with budget coordination."""
    
    def __init__(self, model_router, memory_manager):
        self.model_router = model_router
        self.memory_manager = memory_manager
        self.pipeline: List[LearningPipelineStage] = []
        self.reflection_queue: asyncio.Queue = asyncio.Queue()
        self.is_running = False
        
    def set_pipeline(self, pipeline: List[LearningPipelineStage]):
        self.pipeline = pipeline
        
    async def start(self):
        """Starts the background reflection queue processor."""
        self.is_running = True
        asyncio.create_task(self._process_queue())
        logger.info("LearningEngine started.")
        
    async def stop(self):
        self.is_running = False
        logger.info("LearningEngine stopped.")
        
    async def schedule_learning(self, conversation_id: str, history: List[Dict[str, Any]]):
        """Queues a conversation for learning analysis."""
        context = LearningContext(conversation_id=conversation_id, history=history)
        await self.reflection_queue.put(context)
        logger.debug(f"Queued conversation {conversation_id} for learning.")
        
    async def _process_queue(self):
        while self.is_running:
            try:
                # 1. Check Learning Budget
                # If router is busy with active chat, sleep and defer
                # For this implementation, we simulate checking model load
                # In a real scenario, we'd check `model_router.is_busy()`
                if hasattr(self.model_router, 'is_busy') and self.model_router.is_busy():
                    await asyncio.sleep(5)
                    continue
                    
                context: LearningContext = await asyncio.wait_for(self.reflection_queue.get(), timeout=1.0)
                
                logger.info(f"Processing learning for {context.conversation_id}")
                
                # Execute pipeline
                for stage in self.pipeline:
                    context = await stage.process(context)
                    if context.should_skip:
                        logger.info(f"Learning skipped for {context.conversation_id}: {context.skip_reason}")
                        break
                        
                self.reflection_queue.task_done()
                
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.error(f"Error in learning queue processing: {e}", exc_info=True)
                await asyncio.sleep(1)
