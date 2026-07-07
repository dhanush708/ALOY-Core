import logging
from ..pipeline import LearningContext, LearningPipelineStage

logger = logging.getLogger(__name__)

class DuplicateDetectionStage(LearningPipelineStage):
    """Detects and merges identical or highly similar memories."""
    
    def __init__(self, memory_manager):
        self.memory_manager = memory_manager
        
    async def process(self, context: LearningContext) -> LearningContext:
        unique_candidates = []
        
        for candidate in context.candidates:
            # Check for exact matches or high similarity
            results = await self.memory_manager.retrieve(candidate.content, limit=3)
            
            is_duplicate = False
            for rm in results:
                # Simple exact match or very high score match
                if rm.score > 0.95 and rm.memory.type == candidate.type:
                    is_duplicate = True
                    logger.debug(f"Dropped duplicate candidate: {candidate.content}")
                    # In a full implementation, we might merge/update the existing memory's importance
                    break
                    
            if not is_duplicate:
                unique_candidates.append(candidate)
                
        context.candidates = unique_candidates
        return context
