import logging
from ..pipeline import LearningContext, LearningPipelineStage

logger = logging.getLogger(__name__)

class PromotionStage(LearningPipelineStage):
    """Handles Memory Promotion based on importance and confidence."""
    
    def __init__(self, memory_manager):
        self.memory_manager = memory_manager
        
    async def process(self, context: LearningContext) -> LearningContext:
        for candidate in context.candidates:
            # Insert the new memory into the DB
            # Calculate initial tier based on confidence
            tier = "working"
            if candidate.confidence > 0.9:
                tier = "permanent"
            elif candidate.confidence > 0.7:
                tier = "long_term"
            elif candidate.confidence > 0.5:
                tier = "short_term"
                
            logger.info(f"Learned ({tier}): {candidate.content}")
            
            # Store it using memory manager
            await self.memory_manager.store(
                content=candidate.content,
                memory_type=candidate.type,
                importance=candidate.confidence,  # Map confidence to importance
                tier=tier
            )
            
        return context
