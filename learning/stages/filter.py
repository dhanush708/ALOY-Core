import logging
from ..pipeline import LearningContext, LearningPipelineStage

logger = logging.getLogger(__name__)

class LearningFilterStage(LearningPipelineStage):
    """Filters out conversations that aren't worth learning from."""
    
    async def process(self, context: LearningContext) -> LearningContext:
        # Simple heuristic filter for now
        # Skip if conversation has fewer than 2 turns
        if len(context.history) < 2:
            context.should_skip = True
            context.skip_reason = "Conversation too short"
            return context
            
        # Try to detect trivial intent (e.g. just saying "hi" and "hello")
        user_messages = [m['content'] for m in context.history if m.get('role') == 'user']
        if all(len(m.split()) < 3 for m in user_messages):
            context.should_skip = True
            context.skip_reason = "Trivial conversation"
            
        return context
