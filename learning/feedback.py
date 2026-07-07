import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

class FeedbackProcessor:
    """Processes direct user feedback to update memories."""
    
    def __init__(self, memory_manager):
        self.memory_manager = memory_manager
        
    async def process_feedback(self, feedback_data: Dict[str, Any]):
        """Processes thumbs up/down and explicit corrections."""
        feedback_type = feedback_data.get('type')
        text = feedback_data.get('text')
        message_id = feedback_data.get('message_id')
        
        logger.info(f"Processing feedback {feedback_type} for message {message_id}")
        
        if feedback_type == 'thumbs_down' and text:
            # If there's a correction, we store it as a high-confidence memory
            await self.memory_manager.store(
                content=f"User corrected previous action: {text}",
                memory_type="preference",
                importance=0.9,
                tier="permanent"
            )
